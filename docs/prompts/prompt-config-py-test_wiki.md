You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.shared/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.shared/config/<script_name>.json`)
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

# tests\test_wiki.py
"""Tests for wiki.tools.compile_wiki."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

import wiki.tools.compile_wiki as _mod
from shared.interfaces import VaultWriteError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    kb = tmp_path / "knowledge-base"
    (kb / "00-Inbox").mkdir(parents=True)
    (kb / "01-Processing").mkdir(parents=True)
    (kb / "02-Library").mkdir(parents=True)
    return kb


@pytest.fixture
def patch_roots(vault, tmp_path, monkeypatch):
    """Redirect all module-level path constants to tmp_path layout."""
    from shared.config import VaultPaths

    monkeypatch.setattr(_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(_mod, "_VAULT_ROOT",   vault)
    monkeypatch.setattr(_mod, "_VAULT_PATHS",  VaultPaths(vault_root=vault))
    monkeypatch.setattr(_mod, "_INBOX",        vault / "00-Inbox")
    monkeypatch.setattr(_mod, "_PROCESSING",   vault / "01-Processing")
    monkeypatch.setattr(_mod, "_LIBRARY",      vault / "02-Library")

    agent_state = tmp_path / ".agents" / "wiki" / "state"
    agent_state.mkdir(parents=True)
    logs_dir = agent_state / "logs"
    logs_dir.mkdir()
    master_log = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
    master_log.parent.mkdir(parents=True)
    master_log.touch()

    monkeypatch.setattr(_mod, "_AGENT_STATE", agent_state)
    monkeypatch.setattr(_mod, "_LOGS_DIR",    logs_dir)
    monkeypatch.setattr(_mod, "_MASTER_LOG",  master_log)
    monkeypatch.setattr(_mod, "_BAD_DOCS",    agent_state / "bad-wiki-docs.txt")

    inbox_queue = tmp_path / ".shared" / "state" / "inbox-queue.json"
    inbox_queue.parent.mkdir(parents=True)
    monkeypatch.setattr(_mod, "_INBOX_QUEUE", inbox_queue)

    return vault


def _write_queue(path: Path, entries: dict) -> None:
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# _pending_documents
# ---------------------------------------------------------------------------

class TestPendingDocuments:
    def test_returns_only_document_pending(self, vault, patch_roots, tmp_path):
        doc = tmp_path / "00-Inbox" / "note.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("hello world", encoding="utf-8")

        queue = {
            "00-Inbox/note.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "pending", "wiki": "pending"},
            },
            "00-Inbox/image.png": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "image",
                "agents": {"vision": "pending", "lore": "pending", "classification": "pending", "wiki": "skip"},
            },
        }
        result = _mod._pending_documents(queue, set())
        keys = [r for r, _ in result]
        assert "00-Inbox/note.md" in keys
        assert "00-Inbox/image.png" not in keys

    def test_skips_done_entries(self, vault, patch_roots, tmp_path):
        doc = tmp_path / "00-Inbox" / "done.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("content", encoding="utf-8")

        queue = {
            "00-Inbox/done.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "done", "wiki": "done"},
            }
        }
        result = _mod._pending_documents(queue, set())
        assert result == []

    def test_skips_bad_docs(self, vault, patch_roots, tmp_path):
        doc = tmp_path / "00-Inbox" / "bad.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("content", encoding="utf-8")

        queue = {
            "00-Inbox/bad.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "skip", "wiki": "pending"},
            }
        }
        result = _mod._pending_documents(queue, {"00-Inbox/bad.md"})
        assert result == []

    def test_skips_missing_files(self, vault, patch_roots, tmp_path):
        queue = {
            "00-Inbox/missing.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"wiki": "pending"},
            }
        }
        result = _mod._pending_documents(queue, set())
        assert result == []


# ---------------------------------------------------------------------------
# _enforce_and_write
# ---------------------------------------------------------------------------

class TestEnforceAndWrite:
    def test_enforces_draft_status(self, vault, patch_roots):
        from shared import FrontmatterIO
        fio  = FrontmatterIO()
        out  = vault / "01-Processing" / "test-entity.md"
        llm_output = (
            "---\nid: npc-dark-mage\ntype: npc\nstatus: approved\n"
            "reviewed: true\nquality: 9\ntags:\n  - dark\nrelationships: []\n---\n"
            "## Description\nA dark mage.\n"
        )
        _mod._enforce_and_write(llm_output, "dark-mage-notes.md", out, fio)
        fm, _ = fio.read(out)
        assert fm["status"]   == "draft"
        assert fm["reviewed"] == False
        assert fm["quality"]  == 0

    def test_injects_source_field(self, vault, patch_roots):
        from shared import FrontmatterIO
        fio = FrontmatterIO()
        out = vault / "01-Processing" / "test-source.md"
        _mod._enforce_and_write(
            "---\nid: lore-test\ntype: lore\ntags: []\nrelationships: []\n---\nbody",
            "original-notes.md",
            out,
            fio,
        )
        fm, _ = fio.read(out)
        assert fm["source"] == ["original-notes.md"]

    def test_defaults_invalid_type_to_lore(self, vault, patch_roots):
        from shared import FrontmatterIO
        fio = FrontmatterIO()
        out = vault / "01-Processing" / "test-type.md"
        _mod._enforce_and_write(
            "---\nid: something\ntype: spaceship\ntags: []\nrelationships: []\n---\nbody",
            "notes.md",
            out,
            fio,
        )
        fm, _ = fio.read(out)
        assert fm["type"] == "lore"

    def test_handles_no_frontmatter(self, vault, patch_roots):
        from shared import FrontmatterIO
        fio = FrontmatterIO()
        out = vault / "01-Processing" / "test-nofm.md"
        _mod._enforce_and_write("Just plain text with no frontmatter.", "notes.md", out, fio)
        fm, body = fio.read(out)
        assert fm["status"]   == "draft"
        assert fm["reviewed"] == False
        assert fm["type"]     == "lore"

    def test_ensures_list_fields(self, vault, patch_roots):
        from shared import FrontmatterIO
        fio = FrontmatterIO()
        out = vault / "01-Processing" / "test-lists.md"
        _mod._enforce_and_write(
            "---\nid: npc-test\ntype: npc\ntags: single-string\nrelationships: null\n---\nbody",
            "test.md",
            out,
            fio,
        )
        fm, _ = fio.read(out)
        assert isinstance(fm["tags"], list)
        assert isinstance(fm["relationships"], list)


# ---------------------------------------------------------------------------
# _mark_wiki_done
# ---------------------------------------------------------------------------

class TestMarkWikiDone:
    def test_updates_queue_entry(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / ".shared" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {
            "00-Inbox/note.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "pending", "wiki": "pending"},
            }
        })
        _mod._mark_wiki_done("00-Inbox/note.md")
        updated = json.loads(queue_path.read_text(encoding="utf-8"))
        assert updated["00-Inbox/note.md"]["agents"]["wiki"] == "done"

    def test_tolerates_missing_entry(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / ".shared" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {})
        # Should not raise
        _mod._mark_wiki_done("00-Inbox/nonexistent.md")


# ---------------------------------------------------------------------------
# Batch size enforcement
# ---------------------------------------------------------------------------

class TestBatchSize:
    def test_batch_capped_at_five(self, vault, patch_roots, tmp_path):
        inbox = tmp_path / "00-Inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        queue: dict = {}
        for i in range(8):
            name = f"doc{i:02d}.md"
            (inbox / name).write_text("x" * 200, encoding="utf-8")
            queue[f"00-Inbox/{name}"] = {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "skip", "wiki": "pending"},
            }
        result = _mod._pending_documents(queue, set())[:_mod.BATCH_SIZE]
        assert len(result) == 5


# ---------------------------------------------------------------------------
# main() — LLM offline path
# ---------------------------------------------------------------------------

class TestMainOffline:
    def test_exits_zero_when_llm_offline(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / ".shared" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {
            "00-Inbox/note.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"wiki": "pending"},
            }
        })
        doc = tmp_path / "00-Inbox" / "note.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("A note with enough content to pass the min-chars check." * 3, encoding="utf-8")

        mock_client = MagicMock()
        mock_client.is_available.return_value = False

        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            with pytest.raises(SystemExit) as exc:
                _mod.main()
        assert exc.value.code == 0

    def test_no_pending_exits_zero(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / ".shared" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {})

        mock_client = MagicMock()
        mock_client.is_available.return_value = True

        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            with pytest.raises(SystemExit) as exc:
                _mod.main()
        assert exc.value.code == 0


# ---------------------------------------------------------------------------
# main() — happy path
# ---------------------------------------------------------------------------

class TestMainHappyPath:
    def test_compiles_document_and_marks_done(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / ".shared" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)

        doc = tmp_path / "00-Inbox" / "goblin-chief.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            "# Goblin Chief Mog\nMog leads the Stonefang goblin tribe. "
            "He wields a rusty greataxe and wears bone trophies." * 5,
            encoding="utf-8",
        )
        _write_queue(queue_path, {
            "00-Inbox/goblin-chief.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "pending", "wiki": "pending"},
            }
        })

        llm_response = (
            "---\nid: npc-goblin-chief-mog\ntype: npc\nstatus: approved\n"
            "reviewed: true\nquality: 8\ntags:\n  - goblin\n  - villain\n"
            "relationships:\n  - '[[location-stonefang-caves]]'\n---\n"
            "## Description\nMog is the chief of the Stonefang goblins.\n"
            "## Details\n- Wields a rusty greataxe\n## Hooks\n- Goblins raid the village\n"
            "## Related\n[[location-stonefang-caves]]\n"
        )

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.chat.return_value = llm_response

        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            with patch("time.sleep"):
                with pytest.raises(SystemExit) as exc:
                    _mod.main()

        assert exc.value.code == 0

        # Output file must exist
        out_files = list((vault / "01-Processing").glob("npc-goblin-chief-mog*.md"))
        assert len(out_files) == 1

        # Frontmatter must be enforced
        from shared import FrontmatterIO
        fm, _ = FrontmatterIO().read(out_files[0])
        assert fm["status"]   == "draft"
        assert fm["reviewed"] == False
        assert fm["quality"]  == 0
        assert fm["source"]   == ["goblin-chief.md"]

        # Queue must be marked done
        updated = json.loads(queue_path.read_text(encoding="utf-8"))
        assert updated["00-Inbox/goblin-chief.md"]["agents"]["wiki"] == "done"

    def test_does_not_write_to_library(self, vault, patch_roots, tmp_path):
        """VaultGuard must block any attempt to write into 02-Library/."""
        from shared import VaultGuard
        from shared.config import VaultPaths
        guard = VaultGuard(VaultPaths(vault_root=vault))
        with pytest.raises(VaultWriteError):
            guard.assert_writable(vault / "02-Library" / "some-entity.md")


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .shared/config/
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

