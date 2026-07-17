"""
NexusCampaigns pipeline constraint tests - AGENTS.md compliance.
I am testing file changes.

Validates AGENTS.md rules using shared agent modules:
  - VaultGuard:    agents may not write to 02-Library/ or 00-Inbox/; no self-approval
  - QualityGate:   score formula, library-readiness (quality >= 7, reviewed=True, rels)
  - slug_utils:    valid entity slugs, to_slug, build_entity_slug, extract_wikilinks
  - linking_rules: per-entity-type required outbound link rules (no orphans)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from nexus.shared import (
    VaultGuard, QualityGate, VaultPaths, VaultWriteError,
    to_slug, build_entity_slug, is_valid_slug, extract_wikilinks, wikilink,
    is_orphan, has_required_links, describe_violations, missing_required_groups,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal vault matching NexusCampaigns folder structure."""
    for folder in ("00-Inbox", "01-Processing", "02-Library",
                   "03-Campaigns", "04-Relationships", "05-Assets"):
        (tmp_path / folder).mkdir()
    return tmp_path


@pytest.fixture()
def guard(vault: Path) -> VaultGuard:
    return VaultGuard(VaultPaths(vault_root=vault))


@pytest.fixture()
def gate() -> QualityGate:
    return QualityGate()


# ===========================================================================
# 1. VaultGuard - write-protection rules (AGENTS.md: 02-Library, 00-Inbox)
# ===========================================================================


class TestVaultGuardWriteProtection:
    """Agents may not write directly to 02-Library/ or 00-Inbox/."""

    def test_write_to_library_raises(self, guard: VaultGuard, vault: Path) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_writable(vault / "02-Library" / "npc-test.md")

    def test_write_to_library_subdir_raises(self, guard: VaultGuard, vault: Path) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_writable(vault / "02-Library" / "npcs" / "npc-test.md")

    def test_write_to_inbox_raises(self, guard: VaultGuard, vault: Path) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_writable(vault / "00-Inbox" / "new-file.md")

    def test_write_to_inbox_images_subdir_raises(self, guard: VaultGuard, vault: Path) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_writable(vault / "00-Inbox" / "images" / "A1" / "new.md")

    def test_write_to_processing_allowed(self, guard: VaultGuard, vault: Path) -> None:
        guard.assert_writable(vault / "01-Processing" / "npc-draft.md")

    def test_write_to_campaigns_allowed(self, guard: VaultGuard, vault: Path) -> None:
        guard.assert_writable(vault / "03-Campaigns" / "session-01.md")

    def test_write_to_relationships_allowed(self, guard: VaultGuard, vault: Path) -> None:
        guard.assert_writable(vault / "04-Relationships" / "graph.md")

    def test_write_to_assets_allowed(self, guard: VaultGuard, vault: Path) -> None:
        guard.assert_writable(vault / "05-Assets" / "token.png")


class TestVaultGuardInboxDeletion:
    """Agents may not delete files from 00-Inbox/ (source preservation)."""

    def test_delete_from_inbox_raises(self, guard: VaultGuard, vault: Path) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(vault / "00-Inbox" / "portrait.png")

    def test_delete_from_inbox_images_subdir_raises(self, guard: VaultGuard, vault: Path) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(vault / "00-Inbox" / "images" / "A1" / "hero.png")

    def test_delete_from_processing_allowed(self, guard: VaultGuard, vault: Path) -> None:
        guard.assert_not_inbox_delete(vault / "01-Processing" / "draft.md")

    def test_delete_from_library_allowed(self, guard: VaultGuard, vault: Path) -> None:
        guard.assert_not_inbox_delete(vault / "02-Library" / "entity.md")


class TestVaultGuardSelfApproval:
    """Agents may not set reviewed=True or status='approved' (G3)."""

    def test_reviewed_true_raises(self, guard: VaultGuard) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_not_self_approved({"reviewed": True, "status": "draft"})

    def test_status_approved_raises(self, guard: VaultGuard) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_not_self_approved({"reviewed": False, "status": "approved"})

    def test_both_forbidden_raises(self, guard: VaultGuard) -> None:
        with pytest.raises(VaultWriteError):
            guard.assert_not_self_approved({"reviewed": True, "status": "approved"})

    def test_draft_status_allowed(self, guard: VaultGuard) -> None:
        guard.assert_not_self_approved({"reviewed": False, "status": "draft"})

    def test_reviewed_false_allowed(self, guard: VaultGuard) -> None:
        guard.assert_not_self_approved({"reviewed": False})

    def test_empty_frontmatter_allowed(self, guard: VaultGuard) -> None:
        guard.assert_not_self_approved({})


# ===========================================================================
# 2. QualityGate - library promotion (AGENTS.md: quality >= 7)
# ===========================================================================


class TestQualityGateScoring:
    """Score formula: +2 per satisfied criterion, max 10."""

    def test_empty_scores_zero(self, gate: QualityGate) -> None:
        assert gate.score({}, "") == 0

    def test_description_section_adds_two(self, gate: QualityGate) -> None:
        assert gate.score({}, "## Description\nSome text.") == 2

    def test_description_case_insensitive(self, gate: QualityGate) -> None:
        assert gate.score({}, "## DESCRIPTION\nText.") == 2

    def test_wikilink_in_relationships_adds_two(self, gate: QualityGate) -> None:
        assert gate.score({"relationships": ["[[npc-hero]]"]}, "") == 2

    def test_wikilink_in_body_adds_two(self, gate: QualityGate) -> None:
        assert gate.score({}, "See [[npc-hero]] for details.") == 2

    def test_three_tags_adds_two(self, gate: QualityGate) -> None:
        assert gate.score({"tags": ["a", "b", "c"]}, "") == 2

    def test_two_tags_insufficient(self, gate: QualityGate) -> None:
        assert gate.score({"tags": ["a", "b"]}, "") == 0

    def test_type_set_adds_two(self, gate: QualityGate) -> None:
        assert gate.score({"type": "npc"}, "") == 2

    def test_source_set_adds_two(self, gate: QualityGate) -> None:
        assert gate.score({"source": ["portrait.png"]}, "") == 2

    def test_all_criteria_scores_ten(self, gate: QualityGate) -> None:
        fm = {
            "type": "npc",
            "tags": ["undead", "villain", "necromancer"],
            "source": ["necromancer.png"],
            "relationships": ["[[location-black-hollow]]"],
        }
        body = "## Description\nAn ancient necromancer.\n[[faction-cult-of-undying]]"
        assert gate.score(fm, body) == 10

    def test_score_capped_at_ten(self, gate: QualityGate) -> None:
        fm = {
            "type": "npc",
            "tags": ["a", "b", "c", "d"],
            "source": ["img.png"],
            "relationships": ["[[x]]", "[[y]]"],
        }
        body = "## Description\n[[z]]"
        assert gate.score(fm, body) <= 10


class TestQualityGateLibraryReadiness:
    """Library promotion requires: quality >= 7, reviewed=True, relationships non-empty."""

    def test_quality_7_reviewed_with_rels_is_ready(self, gate: QualityGate) -> None:
        fm = {"quality": 7, "reviewed": True, "relationships": ["[[loc-x]]"]}
        assert gate.is_library_ready(fm) is True

    def test_quality_10_reviewed_with_rels_is_ready(self, gate: QualityGate) -> None:
        fm = {"quality": 10, "reviewed": True, "relationships": ["[[loc-x]]"]}
        assert gate.is_library_ready(fm) is True

    def test_quality_6_not_ready(self, gate: QualityGate) -> None:
        fm = {"quality": 6, "reviewed": True, "relationships": ["[[loc-x]]"]}
        assert gate.is_library_ready(fm) is False

    def test_not_reviewed_not_ready(self, gate: QualityGate) -> None:
        fm = {"quality": 9, "reviewed": False, "relationships": ["[[loc-x]]"]}
        assert gate.is_library_ready(fm) is False

    def test_empty_relationships_not_ready(self, gate: QualityGate) -> None:
        fm = {"quality": 8, "reviewed": True, "relationships": []}
        assert gate.is_library_ready(fm) is False

    def test_missing_relationships_not_ready(self, gate: QualityGate) -> None:
        fm = {"quality": 8, "reviewed": True}
        assert gate.is_library_ready(fm) is False

    @pytest.mark.parametrize("quality", [0, 1, 3, 5, 6])
    def test_low_quality_not_ready(self, gate: QualityGate, quality: int) -> None:
        fm = {"quality": quality, "reviewed": True, "relationships": ["[[x]]"]}
        assert gate.is_library_ready(fm) is False


# ===========================================================================
# 3. Slug utilities - naming convention (AGENTS.md: {type}-{descriptors})
# ===========================================================================


class TestSlugConvention:
    """Entity filenames follow {type}-{descriptors} slug format."""

    @pytest.mark.parametrize("text,expected", [
        ("Black Hollow Cemetery", "black-hollow-cemetery"),
        ("Necromancer", "necromancer"),
        ("My NPC #1", "my-npc-1"),
        ("Père Noël", "pere-noel"),
        ("   Leading Space  ", "leading-space"),
    ])
    def test_to_slug(self, text: str, expected: str) -> None:
        assert to_slug(text) == expected

    @pytest.mark.parametrize("etype,descriptors,expected", [
        ("npc", ("Necromancer", "Black Hollow"), "npc-necromancer-black-hollow"),
        ("location", ("Dungeon Cirit 01",), "location-dungeon-cirit-01"),
        ("quest", ("Missing Villagers",), "quest-missing-villagers"),
        ("faction", ("Cult of Undying",), "faction-cult-of-undying"),
        ("item", ("Artifact", "Ring"), "item-artifact-ring"),
    ])
    def test_build_entity_slug(
        self, etype: str, descriptors: tuple, expected: str
    ) -> None:
        assert build_entity_slug(etype, *descriptors) == expected

    @pytest.mark.parametrize("slug", [
        "npc-necromancer-black-hollow",
        "quest-missing-villagers",
        "location-black-hollow-cemetery",
        "faction-cult-of-undying",
        "item-ring-of-shadows",
        "creature-goblin-chief",
    ])
    def test_valid_slugs_accepted(self, slug: str) -> None:
        assert is_valid_slug(slug) is True

    @pytest.mark.parametrize("slug", [
        "final_v2-boss",
        "NewNPC",
        "npc new",
        "npc_hero",
        "coolplace",
        "orphan",
        "untitled-npc",
        "newnpc-warrior",
    ])
    def test_invalid_slugs_rejected(self, slug: str) -> None:
        assert is_valid_slug(slug) is False


class TestWikilinkFormat:
    """Internal links must use [[slug]] format."""

    def test_basic_wikilink(self) -> None:
        assert extract_wikilinks("See [[npc-hero]].") == ["npc-hero"]

    def test_multiple_wikilinks(self) -> None:
        links = extract_wikilinks("[[npc-hero]] visited [[location-tavern]].")
        assert links == ["npc-hero", "location-tavern"]

    def test_alias_wikilink_returns_target(self) -> None:
        assert extract_wikilinks("[[npc-hero|The Hero]]") == ["npc-hero"]

    def test_heading_wikilink_returns_target(self) -> None:
        assert extract_wikilinks("[[npc-hero#Backstory]]") == ["npc-hero"]

    def test_deduplication(self) -> None:
        assert extract_wikilinks("[[npc-a]] and [[npc-a]] again") == ["npc-a"]

    def test_no_links_returns_empty(self) -> None:
        assert extract_wikilinks("No links here.") == []

    def test_wikilink_builder(self) -> None:
        assert wikilink("npc-necromancer") == "[[npc-necromancer]]"


# ===========================================================================
# 4. Linking rules - no orphans (AGENTS.md: every entity links to ≥1 other)
# ===========================================================================


class TestOrphanDetection:
    """Every entity must link to at least one other entity."""

    def test_zero_links_is_orphan(self) -> None:
        assert is_orphan([]) is True

    def test_one_link_not_orphan(self) -> None:
        assert is_orphan(["location-black-hollow"]) is False

    def test_multiple_links_not_orphan(self) -> None:
        assert is_orphan(["location-x", "npc-y"]) is False


class TestRequiredLinkRules:
    """Per-entity-type required outbound links from linking-rules.spec.md."""

    @pytest.mark.parametrize("entity_type,links,should_pass", [
        # npc / character: needs location OR faction OR quest
        ("npc",       ["location-black-hollow"],       True),
        ("npc",       ["faction-cult"],                True),
        ("npc",       ["quest-rescue"],                True),
        ("npc",       [],                              False),
        ("character", ["location-ruins"],              True),
        ("character", [],                              False),
        # quest: needs NPC AND location
        ("quest",     ["npc-hero", "location-cave"],   True),
        ("quest",     ["npc-hero"],                    False),
        ("quest",     ["location-cave"],               False),
        ("quest",     [],                              False),
        # location family: needs NPC or faction
        ("location",  ["npc-guard"],                   True),
        ("location",  ["faction-guild"],               True),
        ("location",  [],                              False),
        ("dungeon",   ["creature-goblin"],             True),
        ("dungeon",   [],                              False),
        # faction: needs NPC AND location
        ("faction",   ["npc-hero", "location-hq"],     True),
        ("faction",   ["npc-hero"],                    False),
        ("faction",   [],                              False),
        # item / artifact: needs quest or NPC
        ("item",      ["quest-main"],                  True),
        ("item",      ["npc-owner"],                   True),
        ("item",      [],                              False),
        ("artifact",  ["quest-relic"],                 True),
        ("artifact",  [],                              False),
        # encounter: needs location AND creature
        ("encounter", ["location-cave", "creature-goblin"], True),
        ("encounter", ["location-cave"],               False),
        ("encounter", ["creature-goblin"],             False),
        ("encounter", [],                              False),
        # types with no defined rules
        ("timeline",  [],                              True),
        ("lore",      [],                              True),
        ("event",     [],                              True),
    ])
    def test_required_links(
        self, entity_type: str, links: list[str], should_pass: bool
    ) -> None:
        result = has_required_links(entity_type, links)
        assert result == should_pass, (
            f"{entity_type} with links={links}: "
            f"expected {'pass' if should_pass else 'fail'}"
        )

    def test_describe_violations_npc_no_links(self) -> None:
        violations = describe_violations("npc", [])
        assert len(violations) == 1

    def test_describe_violations_quest_missing_location(self) -> None:
        violations = describe_violations("quest", ["npc-hero"])
        labels = " ".join(violations)
        assert any(t in labels for t in ("location", "city", "village", "dungeon"))

    def test_describe_violations_compliant_empty(self) -> None:
        assert describe_violations("npc", ["location-black-hollow"]) == []

    def test_missing_groups_returns_unsatisfied(self) -> None:
        missing = missing_required_groups("quest", ["npc-hero"])
        assert len(missing) == 1
