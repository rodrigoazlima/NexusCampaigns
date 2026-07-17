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
   - Do not include code - only configuration.

---

**Script to analyze:**

# shared\linking_rules.py
"""shared.linking_rules

Enforces linking-rules.spec.md - per-entity-type required outbound link rules.
Pure functions. No I/O. No side effects.

Rules (from spec):
  npc / character       - ≥1 of: location/city/village/dungeon, faction/organization/religion, quest
  quest                 - ≥1 npc/character  AND  ≥1 location/city/village/dungeon
  location/city/village/dungeon - ≥1 of: npc/character, faction/organization/religion
  faction/organization/religion - ≥1 npc/character  AND  ≥1 location/city/village/dungeon
  item / artifact       - ≥1 of: quest, npc/character
  encounter             - ≥1 location/city/village/dungeon  AND  ≥1 creature/monster
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical type alias groups
# ---------------------------------------------------------------------------

_LOCATION_TYPES: frozenset[str] = frozenset({"location", "city", "village", "dungeon"})
_NPC_TYPES:      frozenset[str] = frozenset({"npc", "character"})
_FACTION_TYPES:  frozenset[str] = frozenset({"faction", "organization", "religion"})
_CREATURE_TYPES: frozenset[str] = frozenset({"creature", "monster"})
_QUEST_TYPES:    frozenset[str] = frozenset({"quest"})

# ---------------------------------------------------------------------------
# Required link groups per entity type
#
# Each entry is a list of AND-groups: ALL groups must be satisfied.
# Each frozenset is an OR-group: ANY one matching linked type satisfies it.
# Entity types not listed here have no required-link rules.
# ---------------------------------------------------------------------------

REQUIRED_LINK_GROUPS: dict[str, list[frozenset[str]]] = {
    # npc / character: needs location OR faction OR quest
    "npc":          [_LOCATION_TYPES | _FACTION_TYPES | _QUEST_TYPES],
    "character":    [_LOCATION_TYPES | _FACTION_TYPES | _QUEST_TYPES],
    # quest: needs NPC AND location
    "quest":        [_NPC_TYPES, _LOCATION_TYPES],
    # location family: needs NPC or faction
    "location":     [_NPC_TYPES | _FACTION_TYPES],
    "city":         [_NPC_TYPES | _FACTION_TYPES],
    "village":      [_NPC_TYPES | _FACTION_TYPES],
    "dungeon":      [_NPC_TYPES | _FACTION_TYPES | _CREATURE_TYPES],
    # faction family: needs NPC AND location
    "faction":      [_NPC_TYPES, _LOCATION_TYPES],
    "organization": [_NPC_TYPES, _LOCATION_TYPES],
    "religion":     [_NPC_TYPES | _LOCATION_TYPES],
    # item / artifact: needs quest or owner NPC
    "item":         [_QUEST_TYPES | _NPC_TYPES],
    "artifact":     [_QUEST_TYPES | _NPC_TYPES],
    # encounter: needs location AND creature
    "encounter":    [_LOCATION_TYPES, _CREATURE_TYPES],
}

# Pre-compute sorted labels at module load (frozenset → "a/b/c" string)
_LABEL_MAP: dict[frozenset[str], str] = {}
for _etype, _groups in REQUIRED_LINK_GROUPS.items():
    for _g in _groups:
        if _g not in _LABEL_MAP:
            _LABEL_MAP[_g] = "/".join(sorted(_g))


def _type_from_slug(slug: str) -> str:
    """Infer entity type from slug prefix (first hyphen-delimited segment).

    >>> _type_from_slug("npc-necromancer-black-hollow")
    'npc'
    >>> _type_from_slug("location-dungeon-cirit-01")
    'location'
    >>> _type_from_slug("nodash")
    'nodash'
    """
    return slug.split("-")[0] if "-" in slug else slug


def missing_required_groups(
    entity_type: str,
    linked_slugs: list[str],
) -> list[frozenset[str]]:
    """Return unsatisfied required-link groups for the given entity type.

    Each returned frozenset is one unsatisfied AND-group.
    Empty list → all requirements met (or no rules defined for this type).

    Args:
        entity_type: The ``type`` frontmatter field (e.g. "npc", "quest").
        linked_slugs: All slug targets from the entity's wikilinks.

    >>> missing_required_groups("npc", [])
    [frozenset({'location', 'city', 'village', 'dungeon', 'faction', ...})]
    >>> missing_required_groups("npc", ["location-black-hollow"])
    []
    """
    groups = REQUIRED_LINK_GROUPS.get(entity_type, [])
    if not groups:
        return []
    linked_types = {_type_from_slug(s) for s in linked_slugs}
    return [g for g in groups if not (linked_types & g)]


def is_orphan(linked_slugs: list[str]) -> bool:
    """Return True if the entity has zero outbound wikilinks."""
    return len(linked_slugs) == 0


def has_required_links(entity_type: str, linked_slugs: list[str]) -> bool:
    """Return True if all required link groups are satisfied (or no rules defined)."""
    return len(missing_required_groups(entity_type, linked_slugs)) == 0


def describe_violations(entity_type: str, linked_slugs: list[str]) -> list[str]:
    """Return human-readable descriptions of unsatisfied required link groups.

    Returns [] if compliant or if entity_type has no defined rules.

    >>> describe_violations("quest", [])
    ['missing link to: character/npc', 'missing link to: city/dungeon/location/village']
    >>> describe_violations("unknown-type", [])
    []
    """
    missing = missing_required_groups(entity_type, linked_slugs)
    result: list[str] = []
    for group in missing:
        label = _LABEL_MAP.get(group, "/".join(sorted(group)))
        result.append(f"missing link to: {label}")
    return result


def required_type_boost(
    source_type: str,
    source_linked_slugs: list[str],
    candidate_slug: str,
) -> int:
    """Score bonus for a candidate that satisfies a missing required-link group.

    Returns +5 if the candidate's inferred type fills at least one missing required
    group for the source entity. Returns 0 otherwise.

    Used by WikilinkResolver._score() to prioritise required-type candidates over
    generic keyword matches.

    >>> required_type_boost("npc", [], "location-black-hollow")
    5
    >>> required_type_boost("npc", ["location-cemetery"], "location-black-hollow")
    0
    """
    candidate_type = _type_from_slug(candidate_slug)
    for group in missing_required_groups(source_type, source_linked_slugs):
        if candidate_type in group:
            return 5
    return 0


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

