"""Tests for shared.models — Pydantic data contracts."""

import pytest
from datetime import date, datetime, timezone
from pydantic import ValidationError

from shared.models import (
    AgentMetrics,
    AgentMetricsEntry,
    AgentLogSummary,
    AgentSlots,
    AgentSlotStatus,
    DailyReport,
    Element,
    EntityFrontmatter,
    EntityStatus,
    EntityType,
    Environment,
    GeneratedTokenEntry,
    GeneratedTokens,
    ImageProcessStatus,
    ImageType,
    InboxQueue,
    InboxQueueEntry,
    NPCFrontmatter,
    NPCLLMOutput,
    NPCProcessStatus,
    PF2E_ANCESTRIES,
    PF2E_CLASSES,
    PF2E_CREATURE_TYPES,
    ProcessedImageEntry,
    ProcessedImagesState,
    ProcessedNPCEntry,
    ProcessedNPCs,
    RepairReport,
    RunMetrics,
    ScenarioEntry,
    TagEnrichmentOutput,
    TasksState,
    TaskStateEntry,
    VaultHealthReport,
    VisionClassification,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEntityType:
    def test_all_values_parse(self):
        for val in ["npc", "character", "faction", "location", "city", "village",
                    "dungeon", "item", "artifact", "quest", "encounter", "creature",
                    "monster", "event", "religion", "organization", "timeline", "lore"]:
            assert EntityType(val).value == val

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            EntityType("invalid")


class TestEntityStatus:
    def test_all_values(self):
        for v in ["draft", "review", "approved", "archived"]:
            assert EntityStatus(v).value == v


class TestImageType:
    def test_values(self):
        for v in ["portrait", "body", "battlemap", "scene", "token"]:
            assert ImageType(v)


class TestElement:
    def test_none_variant(self):
        assert Element.none.value == "none"

    def test_fire(self):
        assert Element.fire.value == "fire"


class TestEnvironment:
    def test_dungeon(self):
        assert Environment.dungeon.value == "dungeon"

    def test_none(self):
        assert Environment.none.value == "none"


class TestAgentSlotStatus:
    def test_values(self):
        for v in ["pending", "done", "skip"]:
            assert AgentSlotStatus(v)


# ---------------------------------------------------------------------------
# PF2e vocabulary constants
# ---------------------------------------------------------------------------

class TestPF2eVocabulary:
    def test_human_in_ancestries(self):
        assert "human" in PF2E_ANCESTRIES

    def test_wizard_in_classes(self):
        assert "wizard" in PF2E_CLASSES

    def test_undead_in_creature_types(self):
        assert "undead" in PF2E_CREATURE_TYPES

    def test_none_in_all(self):
        assert "none" in PF2E_ANCESTRIES
        assert "none" in PF2E_CLASSES
        assert "none" in PF2E_CREATURE_TYPES

    def test_frozensets_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            PF2E_ANCESTRIES.add("test")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# VisionClassification
# ---------------------------------------------------------------------------

class TestVisionClassification:
    def test_minimal(self):
        vc = VisionClassification(type=ImageType.portrait)
        assert vc.ancestry == "none"
        assert vc.element == Element.none

    def test_alias_class(self):
        vc = VisionClassification(type=ImageType.portrait, **{"class": "wizard"})
        assert vc.char_class == "wizard"

    def test_populate_by_name(self):
        vc = VisionClassification(type=ImageType.token, char_class="fighter")
        assert vc.char_class == "fighter"

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            VisionClassification(type="invalid_type")


# ---------------------------------------------------------------------------
# NPCLLMOutput
# ---------------------------------------------------------------------------

class TestNPCLLMOutput:
    def test_full(self):
        npc = NPCLLMOutput(name="Mordecai", ancestry="elf", level=5)
        assert npc.name == "Mordecai"
        assert npc.level == 5

    def test_level_bounds(self):
        with pytest.raises(ValidationError):
            NPCLLMOutput(name="x", ancestry="y", level=21)
        with pytest.raises(ValidationError):
            NPCLLMOutput(name="x", ancestry="y", level=0)

    def test_stat_bounds(self):
        with pytest.raises(ValidationError):
            NPCLLMOutput(name="x", ancestry="y", **{"str": 6})
        with pytest.raises(ValidationError):
            NPCLLMOutput(name="x", ancestry="y", **{"dex": -6})

    def test_alias_str(self):
        npc = NPCLLMOutput(name="x", ancestry="y", **{"str": 3, "class": "fighter"})
        assert npc.str_mod == 3
        assert npc.char_class == "fighter"


# ---------------------------------------------------------------------------
# TagEnrichmentOutput
# ---------------------------------------------------------------------------

class TestTagEnrichmentOutput:
    def test_defaults(self):
        out = TagEnrichmentOutput()
        assert out.tags == []
        assert out.type is None

    def test_with_type(self):
        out = TagEnrichmentOutput(tags=["undead", "villain"], type="npc")
        assert len(out.tags) == 2
        assert out.type == "npc"


# ---------------------------------------------------------------------------
# EntityFrontmatter
# ---------------------------------------------------------------------------

class TestEntityFrontmatter:
    def test_minimal_valid(self):
        fm = EntityFrontmatter(
            id="npc-test",
            type=EntityType.npc,
            created=date.today(),
            updated=date.today(),
        )
        assert fm.status == EntityStatus.draft
        assert fm.reviewed is False
        assert fm.quality == 0

    def test_quality_bounds(self):
        with pytest.raises(ValidationError):
            EntityFrontmatter(
                id="x", type=EntityType.npc,
                created=date.today(), updated=date.today(),
                quality=11,
            )
        with pytest.raises(ValidationError):
            EntityFrontmatter(
                id="x", type=EntityType.npc,
                created=date.today(), updated=date.today(),
                quality=-1,
            )

    def test_sha256_optional(self):
        fm = EntityFrontmatter(
            id="npc-x", type=EntityType.npc,
            created=date.today(), updated=date.today(),
            sha256="abc123",
        )
        assert fm.sha256 == "abc123"


# ---------------------------------------------------------------------------
# NPCFrontmatter
# ---------------------------------------------------------------------------

class TestNPCFrontmatter:
    def test_defaults_to_npc_type(self):
        fm = NPCFrontmatter(
            id="npc-y", created=date.today(), updated=date.today()
        )
        assert fm.type == EntityType.npc

    def test_alias_class(self):
        fm = NPCFrontmatter(
            id="npc-z", created=date.today(), updated=date.today(),
            **{"class": "bard"},
        )
        assert fm.char_class == "bard"

    def test_stat_bounds(self):
        with pytest.raises(ValidationError):
            NPCFrontmatter(
                id="npc-z", created=date.today(), updated=date.today(),
                **{"str": 10},
            )


# ---------------------------------------------------------------------------
# AgentSlots
# ---------------------------------------------------------------------------

class TestAgentSlots:
    def test_defaults_all_pending(self):
        s = AgentSlots()
        assert s.vision == AgentSlotStatus.pending
        assert s.lore == AgentSlotStatus.pending

    def test_set_done(self):
        s = AgentSlots(vision=AgentSlotStatus.done)
        assert s.vision == AgentSlotStatus.done


# ---------------------------------------------------------------------------
# InboxQueueEntry / InboxQueue
# ---------------------------------------------------------------------------

class TestInboxQueueEntry:
    def test_image_entry(self):
        entry = InboxQueueEntry(
            ingestedAt=datetime.now(timezone.utc),
            type="image",
            agents=AgentSlots(),
        )
        assert entry.type == "image"

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            InboxQueueEntry(
                ingestedAt=datetime.now(timezone.utc),
                type="video",
                agents=AgentSlots(),
            )


# ---------------------------------------------------------------------------
# ProcessedImageEntry / ProcessedImagesState
# ---------------------------------------------------------------------------

class TestProcessedImageEntry:
    def _make(self, **kw):
        defaults = dict(
            path="00-Inbox/images/test.png",
            processedAt=datetime.now(timezone.utc),
            originalName="test.png",
            type="portrait",
            sha256="abc",
        )
        defaults.update(kw)
        return ProcessedImageEntry(**defaults)

    def test_defaults(self):
        entry = self._make()
        assert entry.ancestry == "none"
        assert entry.isToken is False
        assert entry.status == ImageProcessStatus.ok

    def test_alias_class(self):
        entry = self._make(**{"class": "wizard"})
        assert entry.char_class == "wizard"

    def test_is_token(self):
        entry = self._make(isToken=True)
        assert entry.isToken is True


class TestProcessedImagesState:
    def test_empty_state(self):
        state = ProcessedImagesState()
        assert state.version == 2
        assert state.images == {}
        assert state.pathIndex == {}


# ---------------------------------------------------------------------------
# ProcessedNPCEntry
# ---------------------------------------------------------------------------

class TestProcessedNPCEntry:
    def test_ok_status(self):
        entry = ProcessedNPCEntry(
            imageKey="sha256key",
            scenarioId="s1",
            outputPath="01-Processing/npc-test.md",
            processedAt=datetime.now(timezone.utc),
            status=NPCProcessStatus.ok,
        )
        assert entry.status == NPCProcessStatus.ok


# ---------------------------------------------------------------------------
# ScenarioEntry
# ---------------------------------------------------------------------------

class TestScenarioEntry:
    def test_active_default(self):
        s = ScenarioEntry(id="s1", name="Arc 1", description="desc", arc="A1")
        assert s.active is True


# ---------------------------------------------------------------------------
# GeneratedTokenEntry
# ---------------------------------------------------------------------------

class TestGeneratedTokenEntry:
    def test_fields(self):
        e = GeneratedTokenEntry(
            sourcePath="00-Inbox/images/npc.png",
            tokenPath="00-Inbox/images/npc-token.png",
            generatedAt=datetime.now(timezone.utc),
        )
        assert "token" in e.tokenPath


# ---------------------------------------------------------------------------
# Runtime models
# ---------------------------------------------------------------------------

class TestTaskStateEntry:
    def test_parse_iso(self):
        entry = TaskStateEntry(lastRun="1970-01-01T00:00:00+00:00")
        assert entry.lastRun.year == 1970


# ---------------------------------------------------------------------------
# Metrics models
# ---------------------------------------------------------------------------

class TestRunMetrics:
    def test_defaults(self):
        now = datetime.now(timezone.utc)
        rm = RunMetrics(startedAt=now, finishedAt=now, durationMs=100)
        assert rm.itemsProcessed == 0
        assert rm.itemsFailed == 0


class TestAgentMetricsEntry:
    def test_empty(self):
        ame = AgentMetricsEntry()
        assert ame.runs == []


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------

class TestDailyReport:
    def test_defaults(self):
        dr = DailyReport(generatedAt=datetime.now(timezone.utc), date="2026-06-10")
        assert dr.agentSummaries == {}
        assert isinstance(dr.vaultHealth, VaultHealthReport)


class TestVaultHealthReport:
    def test_empty(self):
        vhr = VaultHealthReport()
        assert vhr.pendingReview == []
        assert vhr.orphans == []
        assert vhr.queueDepth == 0


class TestRepairReport:
    def test_fields(self):
        rr = RepairReport(
            date="2026-06-10",
            generatedAt=datetime.now(timezone.utc),
        )
        assert rr.repairsApplied == 0
        assert rr.fixLabelsDetected == []


class TestAgentLogSummary:
    def test_defaults(self):
        s = AgentLogSummary()
        assert s.runs == 0
        assert s.errors == 0
        assert s.firstRun is None
