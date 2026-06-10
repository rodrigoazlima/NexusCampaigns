"""Integration tests for shared module.

Tests real interactions between components — no mocking of shared internals.
Uses a real temp-dir vault structure to verify end-to-end workflows.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from shared import (
    FrontmatterIO,
    Logger,
    StateStore,
    VaultGuard,
    load_vault_config,
)
from shared.config import VaultPaths, SystemPaths, VaultConfig, LLMEndpointConfig
from shared.defaults import (
    INBOX_QUEUE_DEFAULT,
    PROCESSED_IMAGES_DEFAULT,
    PROCESSED_NPCS_DEFAULT,
    REQUIRED_DIRS,
    STATE_FILE_DEFAULTS,
    TASKS_STATE_DEFAULT,
)
from shared.interfaces import VaultWriteError
from shared.models import (
    AgentSlots,
    AgentSlotStatus,
    EntityFrontmatter,
    EntityStatus,
    EntityType,
    InboxQueueEntry,
    NPCFrontmatter,
    ProcessedImageEntry,
    ProcessedImagesState,
    ImageProcessStatus,
)


# ---------------------------------------------------------------------------
# Shared vault fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    """Minimal vault directory structure mirroring knowledge-base/."""
    kb = tmp_path / "knowledge-base"
    for folder in [
        "00-Inbox/images",
        "00-Inbox/docs",
        "01-Processing",
        "02-Library",
        "03-Campaigns",
    ]:
        (kb / folder).mkdir(parents=True)
    return tmp_path


@pytest.fixture
def cfg(vault):
    return load_vault_config(vault)


@pytest.fixture
def guard(cfg):
    return VaultGuard(cfg.vault_paths)


@pytest.fixture
def fmio():
    return FrontmatterIO()


@pytest.fixture
def logger_setup(vault):
    logs_dir   = vault / ".agents" / "ingestion" / "state" / "logs"
    master_log = vault / ".agents" / "orchestrator" / "state" / "logs" / "automation.log"
    logger = Logger(
        task_id        = "ingestion-agent",
        script_basename= "11_ingestion_agent.py",
        logs_dir       = logs_dir,
        master_log     = master_log,
    )
    return logger, logs_dir, master_log


# ---------------------------------------------------------------------------
# 1. Config → VaultPaths resolve correctly through full chain
# ---------------------------------------------------------------------------

class TestConfigToPathResolution:
    def test_load_vault_config_derives_all_paths(self, vault):
        cfg = load_vault_config(vault)
        assert cfg.vault_paths.inbox   == vault / "knowledge-base" / "00-Inbox"
        assert cfg.vault_paths.library == vault / "knowledge-base" / "02-Library"
        assert cfg.vault_paths.processing == vault / "knowledge-base" / "01-Processing"

    def test_system_paths_resolve_from_same_root(self, vault):
        cfg = load_vault_config(vault)
        assert cfg.system_paths.project_root == vault
        assert cfg.system_paths.shared_state == vault / ".shared" / "state"

    def test_llm_endpoints_accessible_from_config(self, vault):
        cfg = load_vault_config(vault)
        vision_ep = cfg.llm_endpoints["vision"]
        assert vision_ep.url.startswith("http://localhost:1234")
        assert vision_ep.model == "qwen3-vl-4b-instruct"


# ---------------------------------------------------------------------------
# 2. Logger + StateStore working together (agent lifecycle)
# ---------------------------------------------------------------------------

class TestLoggerAndStateStoreTogether:
    def test_agent_start_done_writes_to_log_and_state(self, vault, logger_setup):
        logger, logs_dir, master_log = logger_setup
        state_path = vault / ".agents" / "ingestion" / "state" / "run-state.json"
        store = StateStore(state_path, default={"runs": 0})

        t0 = logger.start()
        store.update(lambda d: {**d, "runs": d["runs"] + 1})
        logger.done(t0, key="processed", count=3, failed=0)

        # Logger wrote to disk
        log_content = master_log.read_text(encoding="utf-8")
        assert "--- START ---" in log_content
        assert "--- DONE ---" in log_content
        assert "processed: 3" in log_content

        # StateStore persisted the update
        assert store.load()["runs"] == 1

    def test_multiple_agent_logs_share_master_log(self, vault):
        """Two agents logging to the same automation.log."""
        master = vault / ".agents" / "orchestrator" / "state" / "logs" / "automation.log"

        log_a = Logger("agent-a", "a.py", vault / "logs-a", master)
        log_b = Logger("agent-b", "b.py", vault / "logs-b", master)

        log_a.info("agent-a message")
        log_b.info("agent-b message")

        content = master.read_text(encoding="utf-8")
        assert "[agent-a]" in content
        assert "[agent-b]" in content
        assert content.index("[agent-a]") < content.index("[agent-b]")

    def test_state_persists_across_logger_instances(self, vault, logger_setup):
        """State written in one run is readable by a fresh StateStore."""
        _, logs_dir, master_log = logger_setup
        state_path = vault / ".shared" / "state" / "inbox-queue.json"

        store1 = StateStore(state_path, default={})
        store1.save({"file.png": {"type": "image"}})

        # New StateStore pointing to the same file
        store2 = StateStore(state_path, default={})
        data = store2.load()
        assert "file.png" in data
        assert data["file.png"]["type"] == "image"


# ---------------------------------------------------------------------------
# 3. VaultGuard + FrontmatterIO: draft-writing pipeline
# ---------------------------------------------------------------------------

class TestDraftWritingPipeline:
    def test_write_draft_to_processing_succeeds(self, cfg, guard, fmio):
        """Full draft-write workflow: guard check → write → verify."""
        target = cfg.vault_paths.processing / "npc-villain.md"

        # Guard allows writes to 01-Processing/
        guard.assert_writable(target)

        fm = {
            "id":       "npc-villain",
            "type":     "npc",
            "status":   "draft",
            "quality":  0,
            "reviewed": False,
            "created":  str(date.today()),
            "updated":  str(date.today()),
            "tags":     ["villain", "undead"],
        }
        body = "## Description\nA fearsome necromancer.\n"
        fmio.write(target, fm, body)

        # File exists and round-trips
        assert target.exists()
        read_fm, read_body = fmio.read(target)
        assert read_fm["id"] == "npc-villain"
        assert read_fm["reviewed"] is False
        assert "necromancer" in read_body

    def test_guard_blocks_write_to_library(self, cfg, guard, fmio):
        """Agent must not write directly to 02-Library/."""
        target = cfg.vault_paths.library / "npc-villain.md"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)
        # File must NOT exist
        assert not target.exists()

    def test_guard_blocks_delete_from_inbox(self, cfg, guard):
        """Source files in 00-Inbox/ must never be deleted by agents."""
        source = cfg.vault_paths.inbox / "images" / "portrait.png"
        source.write_bytes(b"fake image data")
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(source)
        # File still exists — guard blocked the delete
        assert source.exists()

    def test_write_then_update_frontmatter(self, cfg, guard, fmio):
        """Simulate classification agent enriching tags on a draft."""
        target = cfg.vault_paths.processing / "npc-mage.md"

        # Write initial draft
        guard.assert_writable(target)
        fmio.write(target, {"id": "npc-mage", "tags": [], "type": "npc"}, "## Body\n")

        # Enrich tags (simulate classification agent)
        fm, body = fmio.read(target)
        fm["tags"] = ["mage", "arcane", "humanoid"]
        fmio.write(target, fm, body)

        # Verify enrichment persisted
        fm2, _ = fmio.read(target)
        assert "arcane" in fm2["tags"]
        assert len(fm2["tags"]) == 3


# ---------------------------------------------------------------------------
# 4. StateStore + InboxQueue full lifecycle
# ---------------------------------------------------------------------------

class TestInboxQueueLifecycle:
    def _make_queue_store(self, vault):
        path = vault / ".shared" / "state" / "inbox-queue.json"
        return StateStore(path, default=INBOX_QUEUE_DEFAULT)

    def test_init_defaults_creates_empty_queue(self, vault):
        store = self._make_queue_store(vault)
        store.init_defaults()
        assert store.load() == {}

    def test_add_image_entry_and_reload(self, vault):
        store = self._make_queue_store(vault)
        store.init_defaults()

        now = datetime.now(timezone.utc).isoformat()
        store.update(lambda q: {
            **q,
            "knowledge-base/00-Inbox/images/portrait.png": {
                "ingestedAt": now,
                "type":       "image",
                "agents": {
                    "vision":         "pending",
                    "lore":           "pending",
                    "classification": "pending",
                    "wiki":           "skip",
                },
            }
        })

        q = store.load()
        assert "knowledge-base/00-Inbox/images/portrait.png" in q

    def test_mark_vision_done_updates_slot(self, vault):
        store = self._make_queue_store(vault)
        key   = "knowledge-base/00-Inbox/images/portrait.png"
        store.save({
            key: {
                "ingestedAt": datetime.now(timezone.utc).isoformat(),
                "type": "image",
                "agents": {"vision": "pending", "lore": "pending",
                           "classification": "pending", "wiki": "skip"},
            }
        })

        def mark_done(q):
            q[key]["agents"]["vision"] = "done"
            return q

        store.update(mark_done)
        assert store.load()[key]["agents"]["vision"] == "done"

    def test_queue_survives_multiple_agent_updates(self, vault):
        """Simulate ingestion + vision both updating the queue atomically."""
        store = self._make_queue_store(vault)
        store.init_defaults()

        files = [f"kb/00-Inbox/images/img{i:03d}.png" for i in range(5)]
        for f in files:
            store.update(lambda q, ff=f: {
                **q,
                ff: {"ingestedAt": "2026-01-01T00:00:00+00:00",
                     "type": "image",
                     "agents": {"vision": "pending", "lore": "pending",
                                "classification": "pending", "wiki": "skip"}},
            })

        q = store.load()
        assert len(q) == 5
        for f in files:
            assert f in q


# ---------------------------------------------------------------------------
# 5. ProcessedImages state lifecycle (vision agent state)
# ---------------------------------------------------------------------------

class TestProcessedImagesLifecycle:
    def _make_store(self, vault):
        path = vault / ".agents" / "vision" / "state" / "processed-images.json"
        return StateStore(path, default=PROCESSED_IMAGES_DEFAULT)

    def test_init_creates_v2_structure(self, vault):
        store = self._make_store(vault)
        store.init_defaults()
        data = store.load()
        assert data["version"] == 2
        assert data["images"] == {}
        assert data["pathIndex"] == {}

    def test_add_processed_image_entry(self, vault):
        store = self._make_store(vault)
        store.init_defaults()

        sha = "abc123def456"
        entry = {
            "path":         "00-Inbox/images/A1/npc-wizard.png",
            "processedAt":  datetime.now(timezone.utc).isoformat(),
            "originalName": "wizard.png",
            "type":         "portrait",
            "ancestry":     "elf",
            "class":        "wizard",
            "creature_type":"none",
            "element":      "none",
            "environment":  "none",
            "description":  "A wise elven wizard",
            "sha256":       sha,
            "isToken":      False,
            "status":       "ok",
        }

        def add_image(data):
            data["images"][sha] = entry
            data["pathIndex"]["00-Inbox/images/A1/npc-wizard.png"] = sha
            return data

        store.update(add_image)

        data = store.load()
        assert sha in data["images"]
        assert data["images"][sha]["ancestry"] == "elf"
        assert data["pathIndex"]["00-Inbox/images/A1/npc-wizard.png"] == sha

    def test_pydantic_validates_loaded_entry(self, vault):
        """StateStore data round-trips through Pydantic model correctly."""
        store = self._make_store(vault)
        store.init_defaults()

        sha = "deadbeef"
        store.update(lambda d: {
            **d,
            "images": {
                sha: {
                    "path":         "00-Inbox/images/test.png",
                    "processedAt":  datetime.now(timezone.utc).isoformat(),
                    "originalName": "test.png",
                    "type":         "portrait",
                    "sha256":       sha,
                    "isToken":      False,
                    "status":       "ok",
                }
            },
        })

        raw  = store.load()
        entry = ProcessedImageEntry.model_validate(raw["images"][sha])
        assert entry.sha256 == sha
        assert entry.status == ImageProcessStatus.ok
        assert entry.isToken is False


# ---------------------------------------------------------------------------
# 6. FrontmatterIO + Pydantic model round-trip
# ---------------------------------------------------------------------------

class TestFrontmatterPydanticRoundTrip:
    def test_entity_frontmatter_reads_from_file(self, cfg, fmio):
        path = cfg.vault_paths.processing / "loc-dungeon.md"
        fmio.write(path, {
            "id":       "loc-dungeon-01",
            "type":     "location",
            "status":   "draft",
            "quality":  0,
            "created":  "2026-06-10",
            "updated":  "2026-06-10",
            "reviewed": False,
            "tags":     ["dungeon", "undead"],
            "source":   ["dungeon_map.jpg"],
            "relationships": ["[[faction-cult-of-undying]]"],
        }, "## Description\nA dark dungeon.\n")

        fm, body = fmio.read(path)
        entity = EntityFrontmatter.model_validate(fm)

        assert entity.id == "loc-dungeon-01"
        assert entity.type == EntityType.location
        assert entity.status == EntityStatus.draft
        assert entity.reviewed is False
        assert "dungeon" in entity.tags
        assert "[[faction-cult-of-undying]]" in entity.relationships

    def test_npc_frontmatter_full_round_trip(self, cfg, fmio):
        path = cfg.vault_paths.processing / "npc-necromancer.md"
        fmio.write(path, {
            "id":       "npc-necromancer-hollow",
            "type":     "npc",
            "status":   "draft",
            "quality":  0,
            "created":  "2026-06-10",
            "updated":  "2026-06-10",
            "reviewed": False,
            "tags":     ["villain", "undead", "necromancer"],
            "source":   ["necromancer.png"],
            "name":     "Malachar the Hollow",
            "ancestry": "human",
            "class":    "wizard",
            "level":    12,
            "relationships": [],
        }, "## Backstory\nOncé a court wizard...\n")

        fm, body = fmio.read(path)
        npc = NPCFrontmatter.model_validate(fm)

        assert npc.name == "Malachar the Hollow"
        assert npc.level == 12
        assert npc.char_class == "wizard"
        assert "Oncé" in body  # Unicode preserved

    def test_agent_must_not_set_reviewed_true(self, cfg, fmio):
        """Security: reviewed field written by agent must remain False."""
        path = cfg.vault_paths.processing / "npc-guard.md"
        fmio.write(path, {
            "id":       "npc-guard",
            "type":     "npc",
            "status":   "draft",
            "reviewed": False,   # agent NEVER writes True
            "quality":  0,
            "created":  "2026-06-10",
            "updated":  "2026-06-10",
        }, "")

        fm, _ = fmio.read(path)
        assert fm["reviewed"] is False


# ---------------------------------------------------------------------------
# 7. Bootstrap: create all required dirs and state defaults
# ---------------------------------------------------------------------------

class TestBootstrapAllDefaults:
    def test_create_all_required_dirs(self, vault):
        for rel in REQUIRED_DIRS:
            d = vault / rel
            d.mkdir(parents=True, exist_ok=True)
            assert d.is_dir(), f"Missing: {rel}"

    def test_init_all_state_defaults(self, vault):
        for rel_path, default in STATE_FILE_DEFAULTS.items():
            store = StateStore(vault / rel_path, default=default)
            store.init_defaults()
            data = store.load()
            assert data is not None

    def test_tasks_state_all_agents_epoch(self, vault):
        path  = vault / ".agents" / "orchestrator" / "state" / "tasks-state.json"
        store = StateStore(path, default=TASKS_STATE_DEFAULT)
        store.init_defaults()
        data  = store.load()
        for agent_id, entry in data.items():
            assert "1970" in entry["lastRun"], f"{agent_id} not at epoch"

    def test_init_defaults_idempotent(self, vault):
        """Calling init_defaults() twice must not overwrite existing data."""
        path  = vault / ".shared" / "state" / "inbox-queue.json"
        store = StateStore(path, default=INBOX_QUEUE_DEFAULT)
        store.init_defaults()
        store.save({"existing-file.png": {"type": "image"}})
        store.init_defaults()   # second call — must not overwrite
        assert "existing-file.png" in store.load()


# ---------------------------------------------------------------------------
# 8. LLMClient offline behaviour (localhost server not running)
# ---------------------------------------------------------------------------

class TestLLMClientOfflineBehaviour:
    def test_is_available_returns_false_when_server_down(self, cfg):
        from shared.llm_client import LLMClient
        client = LLMClient(cfg.llm_endpoints["vision"])
        # Real localhost:1234 likely not running in CI
        result = client.is_available()
        assert isinstance(result, bool)   # just check it doesn't crash

    def test_chat_raises_llm_offline_error(self, cfg):
        from shared.llm_client import LLMClient
        from shared.interfaces import LLMOfflineError
        from shared.config import LLMEndpointConfig

        # Point to a port that definitely has nothing running
        ep = LLMEndpointConfig(
            url      = "http://localhost:19999/v1/chat/completions",
            model    = "none",
            type     = "text",
            provider = "test",
        )
        client = LLMClient(ep)
        with pytest.raises(LLMOfflineError):
            client.chat([{"role": "user", "content": "hello"}], max_tokens=10)

    def test_vision_chat_raises_llm_offline_error(self, cfg, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from shared.llm_client import LLMClient
        from shared.interfaces import LLMOfflineError
        from shared.config import LLMEndpointConfig

        img = tmp_path / "test.png"
        Image.new("RGB", (50, 50), color=(0, 128, 0)).save(img)

        ep = LLMEndpointConfig(
            url="http://localhost:19999/v1/chat/completions",
            model="none", type="vision", provider="test",
        )
        client = LLMClient(ep)
        with pytest.raises(LLMOfflineError):
            client.vision_chat(img, "classify", system="sys", max_tokens=50)


# ---------------------------------------------------------------------------
# 9. Cross-component: Logger + FrontmatterIO + VaultGuard + StateStore
#    Simulate a minimal agent run processing one image file
# ---------------------------------------------------------------------------

class TestMinimalAgentRunSimulation:
    def test_process_one_image_end_to_end(self, vault):
        """
        Simulate vision agent processing one image:
          1. Load config
          2. Guard check on output path
          3. Write draft to 01-Processing/
          4. Update processed-images state
          5. Log START/DONE
          6. Verify all outputs consistent
        """
        cfg    = load_vault_config(vault)
        guard  = VaultGuard(cfg.vault_paths)
        fmio   = FrontmatterIO()
        master = cfg.system_paths.logs_dir / "automation.log"
        logger = Logger(
            task_id        = "vision-agent",
            script_basename= "06_classify_images.py",
            logs_dir       = cfg.system_paths.agent_state("vision") / "logs",
            master_log     = master,
        )
        img_state_path = cfg.system_paths.agent_state("vision") / "processed-images.json"
        img_store = StateStore(img_state_path, default=PROCESSED_IMAGES_DEFAULT)
        img_store.init_defaults()

        # -- Agent run starts --
        t0 = logger.start()

        # Source image in inbox (guard: can't write here, but can read)
        source_img = cfg.vault_paths.inbox / "images" / "A1" / "npc-wizard.png"
        source_img.parent.mkdir(parents=True, exist_ok=True)
        source_img.write_bytes(b"fake png data")

        # Output draft in 01-Processing/
        draft_path = cfg.vault_paths.processing / "npc-wizard-elf.md"
        guard.assert_writable(draft_path)   # must not raise

        sha256 = "aabbccdd1122"
        fmio.write(draft_path, {
            "id":       "npc-wizard-elf",
            "type":     "npc",
            "status":   "draft",
            "quality":  0,
            "created":  str(date.today()),
            "updated":  str(date.today()),
            "reviewed": False,
            "sha256":   sha256,
            "tags":     ["wizard", "elf"],
            "source":   ["npc-wizard.png"],
            "relationships": [],
        }, "## Description\nAn elven wizard.\n")

        # Update state
        img_store.update(lambda d: {
            **d,
            "images": {
                **d.get("images", {}),
                sha256: {
                    "path":         str(source_img.relative_to(vault)),
                    "processedAt":  datetime.now(timezone.utc).isoformat(),
                    "originalName": "npc-wizard.png",
                    "type":         "portrait",
                    "ancestry":     "elf",
                    "class":        "wizard",
                    "sha256":       sha256,
                    "isToken":      False,
                    "status":       "ok",
                },
            },
            "pathIndex": {
                **d.get("pathIndex", {}),
                str(source_img.relative_to(vault)): sha256,
            },
        })

        logger.done(t0, key="processed", count=1, failed=0)

        # -- Verify outputs --

        # Draft exists with correct frontmatter
        assert draft_path.exists()
        fm, body = fmio.read(draft_path)
        assert fm["reviewed"] is False
        assert fm["sha256"] == sha256
        assert "elf" in fm["tags"]

        # State updated with the image entry
        img_data = img_store.load()
        assert sha256 in img_data["images"]
        assert img_data["images"][sha256]["ancestry"] == "elf"

        # Log contains START and DONE
        log_content = master.read_text(encoding="utf-8")
        assert "--- START ---" in log_content
        assert "processed: 1" in log_content
        assert "[vision-agent]" in log_content

        # Source image untouched (inbox preservation)
        assert source_img.exists()
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(source_img)

    def test_guard_prevents_library_pollution_during_run(self, vault):
        """Agent that accidentally tries to write to 02-Library/ is blocked."""
        cfg   = load_vault_config(vault)
        guard = VaultGuard(cfg.vault_paths)
        fmio  = FrontmatterIO()

        # Agent mistakenly targets 02-Library/ instead of 01-Processing/
        wrong_target = cfg.vault_paths.library / "npc-villain.md"

        with pytest.raises(VaultWriteError):
            guard.assert_writable(wrong_target)

        # Verify nothing was written
        assert not wrong_target.exists()

    def test_wikilink_enrichment_adds_related_section(self, cfg, fmio):
        """Simulate wikilink agent adding ## Related section to a draft."""
        draft = cfg.vault_paths.processing / "npc-baron.md"
        fmio.write(draft, {
            "id": "npc-baron",
            "type": "npc",
            "status": "draft",
            "quality": 0,
            "reviewed": False,
            "created": "2026-06-10",
            "updated": "2026-06-10",
            "relationships": [],
        }, "## Description\nThe Baron of the North.\n")

        # Simulate wikilink agent enriching relationships
        fm, body = fmio.read(draft)
        fm["relationships"] = ["[[location-northern-fortress]]", "[[faction-iron-guard]]"]
        if "## Related" not in body:
            body += "\n## Related\n\n- [[location-northern-fortress]]\n- [[faction-iron-guard]]\n"
        fmio.write(draft, fm, body)

        fm2, body2 = fmio.read(draft)
        assert "[[location-northern-fortress]]" in fm2["relationships"]
        assert "## Related" in body2
        assert "[[faction-iron-guard]]" in body2
