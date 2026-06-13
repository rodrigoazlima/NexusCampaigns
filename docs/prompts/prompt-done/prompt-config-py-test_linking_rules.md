You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.system/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.system/config/<script_name>.json`)
     - Contains script-specific settings and overrides.
     - Always loaded after global config (can override global values).
     - Can be empty (`{}`) but must always exist.

2. **Output Format:**
   - You must output **two valid JSON objects** clearly labeled.
   - Use sensible, descriptive keys in `snake_case`.
   - Include meaningful `default` values for every setting.
   - Add a `"description"` field for each major setting when helpful.
   - Group related settings under logical sections if needed.

3. **What to Extract:**
   - Hardcoded paths (especially those derived from `__file__`)
   - Constants (BATCH_SIZE, thresholds, limits, etc.)
   - LLM settings (URL, model, provider, etc.)
   - File/directory references
   - Magic numbers and strings that are likely to change
   - Any environment-dependent behavior

4. **Rules:**
   - Prefer putting common things (project roots, LLM config, logging, shared directories) in **global**.
   - Put script-specific behavior (batch sizes, task-specific prompts, agent name, etc.) in **local**.
   - Make sure the JSONs contain good defaults so the script works even if the files are deleted.
   - Use clear, consistent naming.
   - Do not include code — only configuration.

---

**Script to analyze:**

# tests\test_linking_rules.py
"""Tests for shared.linking_rules (linking-rules.spec.md enforcement)."""

import sys
from pathlib import Path

import pytest

_AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared.linking_rules import (
    REQUIRED_LINK_GROUPS,
    describe_violations,
    has_required_links,
    is_orphan,
    missing_required_groups,
    required_type_boost,
    _type_from_slug,
)


# ---------------------------------------------------------------------------
# _type_from_slug
# ---------------------------------------------------------------------------

class TestTypeFromSlug:
    def test_npc_slug(self):
        assert _type_from_slug("npc-necromancer-black-hollow") == "npc"

    def test_location_slug(self):
        assert _type_from_slug("location-dungeon-cirit-01") == "location"

    def test_single_segment(self):
        assert _type_from_slug("nodash") == "nodash"

    def test_short_slug(self):
        assert _type_from_slug("quest-main") == "quest"

    def test_creature_slug(self):
        assert _type_from_slug("creature-wyvern-elder") == "creature"


# ---------------------------------------------------------------------------
# is_orphan
# ---------------------------------------------------------------------------

class TestIsOrphan:
    def test_empty_list_is_orphan(self):
        assert is_orphan([]) is True

    def test_nonempty_list_not_orphan(self):
        assert is_orphan(["location-cemetery"]) is False

    def test_single_link(self):
        assert is_orphan(["quest-missing-villagers"]) is False


# ---------------------------------------------------------------------------
# missing_required_groups — npc
# ---------------------------------------------------------------------------

class TestMissingRequiredGroupsNPC:
    def test_npc_no_links_returns_one_group(self):
        missing = missing_required_groups("npc", [])
        assert len(missing) == 1

    def test_npc_with_location_satisfies(self):
        missing = missing_required_groups("npc", ["location-black-hollow"])
        assert missing == []

    def test_npc_with_city_satisfies(self):
        missing = missing_required_groups("npc", ["city-ironhaven"])
        assert missing == []

    def test_npc_with_faction_satisfies(self):
        missing = missing_required_groups("npc", ["faction-cult-undying"])
        assert missing == []

    def test_npc_with_quest_satisfies(self):
        missing = missing_required_groups("npc", ["quest-missing-villagers"])
        assert missing == []

    def test_npc_with_unrelated_type_still_missing(self):
        missing = missing_required_groups("npc", ["item-sword-of-doom"])
        assert len(missing) == 1

    def test_character_same_rules_as_npc(self):
        assert (
            missing_required_groups("character", [])
            == missing_required_groups("npc", [])
        )


# ---------------------------------------------------------------------------
# missing_required_groups — quest
# ---------------------------------------------------------------------------

class TestMissingRequiredGroupsQuest:
    def test_quest_no_links_two_groups_missing(self):
        missing = missing_required_groups("quest", [])
        assert len(missing) == 2

    def test_quest_only_npc_still_missing_location(self):
        missing = missing_required_groups("quest", ["npc-villain"])
        assert len(missing) == 1
        # remaining group should contain location types
        assert "location" in missing[0]

    def test_quest_only_location_still_missing_npc(self):
        missing = missing_required_groups("quest", ["location-dungeon-cirit"])
        assert len(missing) == 1
        assert "npc" in missing[0]

    def test_quest_with_both_fully_satisfied(self):
        missing = missing_required_groups(
            "quest", ["npc-villain", "location-dungeon-cirit"]
        )
        assert missing == []

    def test_quest_character_counts_as_npc(self):
        missing = missing_required_groups(
            "quest", ["character-hero", "location-village-start"]
        )
        assert missing == []


# ---------------------------------------------------------------------------
# missing_required_groups — location
# ---------------------------------------------------------------------------

class TestMissingRequiredGroupsLocation:
    def test_location_no_links_one_group_missing(self):
        missing = missing_required_groups("location", [])
        assert len(missing) == 1

    def test_location_with_npc_satisfies(self):
        assert missing_required_groups("location", ["npc-guard"]) == []

    def test_location_with_faction_satisfies(self):
        assert missing_required_groups("location", ["faction-iron-guild"]) == []

    def test_location_with_item_not_satisfied(self):
        missing = missing_required_groups("location", ["item-sword"])
        assert len(missing) == 1

    def test_city_same_rules_as_location(self):
        assert (
            missing_required_groups("city", [])
            == missing_required_groups("location", [])
        )

    def test_village_same_rules_as_location(self):
        assert (
            missing_required_groups("village", [])
            == missing_required_groups("location", [])
        )


# ---------------------------------------------------------------------------
# missing_required_groups — faction
# ---------------------------------------------------------------------------

class TestMissingRequiredGroupsFaction:
    def test_faction_needs_npc_and_location(self):
        missing = missing_required_groups("faction", [])
        assert len(missing) == 2

    def test_faction_fully_satisfied(self):
        assert missing_required_groups(
            "faction", ["npc-priest", "location-temple"]
        ) == []

    def test_organization_same_as_faction(self):
        assert (
            missing_required_groups("organization", [])
            == missing_required_groups("faction", [])
        )


# ---------------------------------------------------------------------------
# missing_required_groups — item / artifact
# ---------------------------------------------------------------------------

class TestMissingRequiredGroupsItem:
    def test_item_no_links_one_group_missing(self):
        assert len(missing_required_groups("item", [])) == 1

    def test_item_with_quest_satisfies(self):
        assert missing_required_groups("item", ["quest-main-arc"]) == []

    def test_item_with_npc_satisfies(self):
        assert missing_required_groups("item", ["npc-owner"]) == []

    def test_artifact_same_as_item(self):
        assert (
            missing_required_groups("artifact", [])
            == missing_required_groups("item", [])
        )


# ---------------------------------------------------------------------------
# missing_required_groups — encounter
# ---------------------------------------------------------------------------

class TestMissingRequiredGroupsEncounter:
    def test_encounter_needs_location_and_creature(self):
        missing = missing_required_groups("encounter", [])
        assert len(missing) == 2

    def test_encounter_with_location_and_creature_satisfied(self):
        assert missing_required_groups(
            "encounter", ["location-dungeon-01", "creature-goblin"]
        ) == []

    def test_encounter_monster_counts_as_creature(self):
        assert missing_required_groups(
            "encounter", ["location-cave", "monster-troll"]
        ) == []


# ---------------------------------------------------------------------------
# missing_required_groups — unregistered type
# ---------------------------------------------------------------------------

class TestMissingRequiredGroupsUnknown:
    def test_unknown_type_no_rules(self):
        assert missing_required_groups("lore", []) == []

    def test_timeline_no_rules(self):
        assert missing_required_groups("timeline", []) == []

    def test_event_no_rules(self):
        assert missing_required_groups("event", []) == []


# ---------------------------------------------------------------------------
# has_required_links
# ---------------------------------------------------------------------------

class TestHasRequiredLinks:
    def test_false_when_npc_has_no_links(self):
        assert has_required_links("npc", []) is False

    def test_true_when_npc_has_location(self):
        assert has_required_links("npc", ["location-graveyard"]) is True

    def test_true_for_unknown_type(self):
        assert has_required_links("lore", []) is True

    def test_false_when_quest_only_has_npc(self):
        assert has_required_links("quest", ["npc-villain"]) is False

    def test_true_when_quest_has_both(self):
        assert has_required_links("quest", ["npc-villain", "location-dungeon"]) is True


# ---------------------------------------------------------------------------
# describe_violations
# ---------------------------------------------------------------------------

class TestDescribeViolations:
    def test_returns_empty_for_compliant_npc(self):
        assert describe_violations("npc", ["location-hollow"]) == []

    def test_returns_message_for_orphan_npc(self):
        violations = describe_violations("npc", [])
        assert len(violations) == 1
        assert "missing link to:" in violations[0]

    def test_quest_two_messages_when_no_links(self):
        violations = describe_violations("quest", [])
        assert len(violations) == 2
        assert all("missing link to:" in v for v in violations)

    def test_unknown_type_returns_empty(self):
        assert describe_violations("lore", []) == []

    def test_encounter_two_groups_when_empty(self):
        violations = describe_violations("encounter", [])
        assert len(violations) == 2


# ---------------------------------------------------------------------------
# required_type_boost
# ---------------------------------------------------------------------------

class TestRequiredTypeBoost:
    def test_location_candidate_boosts_npc_missing_location(self):
        boost = required_type_boost("npc", [], "location-graveyard")
        assert boost == 5

    def test_faction_candidate_boosts_npc(self):
        boost = required_type_boost("npc", [], "faction-dark-guild")
        assert boost == 5

    def test_quest_candidate_boosts_npc(self):
        boost = required_type_boost("npc", [], "quest-shadow-hunt")
        assert boost == 5

    def test_no_boost_when_npc_already_has_location(self):
        boost = required_type_boost("npc", ["location-hollow"], "location-other")
        assert boost == 0

    def test_no_boost_for_irrelevant_candidate(self):
        # npc needs location/faction/quest — item candidate should give 0
        boost = required_type_boost("npc", [], "item-magic-sword")
        assert boost == 0

    def test_quest_missing_location_boosts_location_candidate(self):
        # quest has npc but missing location
        boost = required_type_boost("quest", ["npc-villain"], "location-dungeon")
        assert boost == 5

    def test_quest_missing_npc_no_boost_for_location(self):
        # quest has location but missing npc — location candidate doesn't help
        boost = required_type_boost("quest", ["location-dungeon"], "location-cave")
        assert boost == 0

    def test_unknown_source_type_no_boost(self):
        boost = required_type_boost("lore", [], "npc-villain")
        assert boost == 0

    def test_encounter_creature_candidate_boosts(self):
        boost = required_type_boost("encounter", ["location-dungeon"], "creature-spider")
        assert boost == 5

    def test_encounter_no_boost_when_both_satisfied(self):
        boost = required_type_boost(
            "encounter",
            ["location-dungeon", "creature-spider"],
            "creature-rat",
        )
        assert boost == 0


# ---------------------------------------------------------------------------
# REQUIRED_LINK_GROUPS coverage — all spec-mandated types present
# ---------------------------------------------------------------------------

class TestRequiredLinkGroupsCoverage:
    def test_spec_types_present(self):
        spec_types = {"npc", "quest", "location", "faction", "item", "encounter"}
        for t in spec_types:
            assert t in REQUIRED_LINK_GROUPS, f"{t!r} missing from REQUIRED_LINK_GROUPS"

    def test_all_groups_are_frozensets(self):
        for etype, groups in REQUIRED_LINK_GROUPS.items():
            for g in groups:
                assert isinstance(g, frozenset), f"Group for {etype!r} is not a frozenset"


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .system/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```

### Bonus: Loader Code Suggestion (for `shared/config.py`)

You can later create a simple loader like this:

```python
from pathlib import Path
import json

def load_config(script_path: Path):
    project_root = Path(__file__).resolve().parents[2]  # adjust as needed
    
    # Global
    global_path = project_root / "config" / "global.json"
    global_cfg = json.loads(global_path.read_text()) if global_path.exists() else {}
    
    # Local
    script_name = script_path.stem
    local_path = project_root / "config" / f"{script_name}.json"
    local_cfg = json.loads(local_path.read_text()) if local_path.exists() else {}
    
    # Merge (local overrides global)
    config = {**global_cfg, **local_cfg}
    return config
```

