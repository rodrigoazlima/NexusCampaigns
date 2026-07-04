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

    agent_state = tmp_path / "agents" / "wiki" / "state"
    agent_state.mkdir(parents=True)
    logs_dir = agent_state / "logs"
    logs_dir.mkdir()
    master_log = tmp_path / "agents" / "runtime" / "state" / "logs" / "automation.log"
    master_log.parent.mkdir(parents=True)
    master_log.touch()

    monkeypatch.setattr(_mod, "_AGENT_STATE", agent_state)
    monkeypatch.setattr(_mod, "_LOGS_DIR",    logs_dir)
    monkeypatch.setattr(_mod, "_MASTER_LOG",  master_log)
    monkeypatch.setattr(_mod, "_BAD_DOCS",    agent_state / "bad-wiki-docs.txt")

    inbox_queue = tmp_path / "system" / "state" / "inbox-queue.json"
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
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
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
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
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
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
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
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
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
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
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


# ---------------------------------------------------------------------------
# _allowed_types constants
# ---------------------------------------------------------------------------

class TestAllowedTypes:
    def test_count(self):
        assert len(_mod._ALLOWED_TYPES) == 18

    def test_core_types_present(self):
        for t in ("npc", "character", "faction", "location", "dungeon", "lore", "item", "artifact"):
            assert t in _mod._ALLOWED_TYPES

    def test_approved_not_in_types(self):
        assert "approved" not in _mod._ALLOWED_TYPES

    def test_draft_not_in_types(self):
        assert "draft" not in _mod._ALLOWED_TYPES


# ---------------------------------------------------------------------------
# _canon_context
# ---------------------------------------------------------------------------

class TestCanonContext:
    def test_empty_when_no_library(self, vault, patch_roots):
        import shutil
        shutil.rmtree(vault / "02-Library")
        assert _mod._canon_context() == ""

    def test_empty_when_library_has_no_md(self, vault, patch_roots):
        (vault / "02-Library" / "image.png").touch()
        assert _mod._canon_context() == ""

    def test_includes_entity_id_and_type(self, vault, patch_roots):
        import yaml
        lib = vault / "02-Library"
        fm = {"id": "npc-dark-lord", "type": "npc", "tags": ["villain"], "relationships": []}
        fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
        (lib / "npc-dark-lord.md").write_text(f"---\n{fm_str}---\n", encoding="utf-8")
        ctx = _mod._canon_context()
        assert "npc-dark-lord" in ctx
        assert "npc" in ctx

    def test_includes_tags_and_rels(self, vault, patch_roots):
        import yaml
        lib = vault / "02-Library"
        fm = {
            "id": "location-ruins",
            "type": "location",
            "tags": ["ancient", "dark"],
            "relationships": ["[[npc-dark-lord]]"],
        }
        fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
        (lib / "location-ruins.md").write_text(f"---\n{fm_str}---\n", encoding="utf-8")
        ctx = _mod._canon_context()
        assert "ancient" in ctx
        assert "npc-dark-lord" in ctx

    def test_caps_at_fifty_entities(self, vault, patch_roots):
        import yaml
        lib = vault / "02-Library"
        for i in range(60):
            fm = {"id": f"npc-test-{i:02d}", "type": "npc", "tags": [], "relationships": []}
            fm_str = yaml.dump(fm)
            (lib / f"npc-test-{i:02d}.md").write_text(f"---\n{fm_str}---\n", encoding="utf-8")
        ctx = _mod._canon_context()
        lines = [ln for ln in ctx.splitlines() if ln.strip()]
        assert len(lines) == 50


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_removes_html_tags(self):
        result = _mod._strip_html("<p>Hello <b>world</b></p>")
        assert result == "Hello world"

    def test_removes_style_blocks(self):
        result = _mod._strip_html('<span style="color:red">text</span>')
        assert "color" not in result
        assert "text" in result

    def test_passthrough_clean_text(self):
        text = "Just plain markdown text."
        assert _mod._strip_html(text) == text

    def test_strips_multiline_tags(self):
        html = "<div\n  class='x'>content</div>"
        result = _mod._strip_html(html)
        assert "content" in result
        assert "<div" not in result


# ---------------------------------------------------------------------------
# _unique_output — collision handling
# ---------------------------------------------------------------------------

class TestUniqueOutput:
    def test_no_collision_returns_plain_slug(self, vault, patch_roots):
        out = _mod._unique_output("npc-test-entity")
        assert out == vault / "01-Processing" / "npc-test-entity.md"

    def test_collision_adds_date_suffix(self, vault, patch_roots):
        from datetime import date
        (vault / "01-Processing" / "npc-test-entity.md").touch()
        out = _mod._unique_output("npc-test-entity")
        today = date.today().strftime("%Y%m%d")
        assert today in out.name

    def test_double_collision_adds_counter(self, vault, patch_roots):
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        (vault / "01-Processing" / "npc-test-entity.md").touch()
        (vault / "01-Processing" / f"npc-test-entity-{today}.md").touch()
        out = _mod._unique_output("npc-test-entity")
        assert "01" in out.name

    def test_creates_processing_dir(self, vault, patch_roots):
        import shutil
        shutil.rmtree(vault / "01-Processing")
        out = _mod._unique_output("npc-test-entity")
        assert out.parent.exists()


# ---------------------------------------------------------------------------
# Short-file skip (< 100 chars → marked done, NOT bad)
# ---------------------------------------------------------------------------

class TestShortFileSkip:
    def test_short_file_marked_done_not_bad(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)

        short_doc = tmp_path / "00-Inbox" / "short.md"
        short_doc.parent.mkdir(parents=True, exist_ok=True)
        short_doc.write_text("Too short.", encoding="utf-8")

        _write_queue(queue_path, {
            "00-Inbox/short.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "skip", "wiki": "pending"},
            }
        })

        mock_client = MagicMock()
        mock_client.is_available.return_value = True

        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            with pytest.raises(SystemExit) as exc:
                _mod.main()

        assert exc.value.code == 0
        # LLM never called for short file
        mock_client.chat.assert_not_called()
        # Queue entry marked done
        updated = json.loads(queue_path.read_text(encoding="utf-8"))
        assert updated["00-Inbox/short.md"]["agents"]["wiki"] == "done"
        # NOT in bad-wiki-docs
        bad_docs_path = tmp_path / "agents" / "wiki" / "state" / "bad-wiki-docs.txt"
        if bad_docs_path.exists():
            bad = bad_docs_path.read_text(encoding="utf-8")
            assert "short.md" not in bad


# ---------------------------------------------------------------------------
# Content truncation at 6000 chars
# ---------------------------------------------------------------------------

class TestContentTruncation:
    def test_long_content_truncated_in_prompt(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)

        long_doc = tmp_path / "00-Inbox" / "long-doc.md"
        long_doc.parent.mkdir(parents=True, exist_ok=True)
        long_doc.write_text("A " * 4000, encoding="utf-8")  # 8000 chars

        _write_queue(queue_path, {
            "00-Inbox/long-doc.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "skip", "wiki": "pending"},
            }
        })

        captured_prompt = {}

        def fake_chat(messages, **kwargs):
            captured_prompt["text"] = messages[0]["content"]
            return (
                "---\nid: lore-test\ntype: lore\nstatus: draft\nquality: 0\n"
                "tags: []\nsource: []\nreviewed: false\nrelationships: []\n---\nbody"
            )

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.chat.side_effect = fake_chat

        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            with patch("time.sleep"):
                with pytest.raises(SystemExit):
                    _mod.main()

        assert "content truncated" in captured_prompt.get("text", "")


# ---------------------------------------------------------------------------
# LLM error → file recorded in bad-wiki-docs
# ---------------------------------------------------------------------------

class TestLLMErrorHandling:
    def test_llm_response_error_records_bad_doc(self, vault, patch_roots, tmp_path):
        from shared import LLMResponseError
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)

        doc = tmp_path / "00-Inbox" / "broken-doc.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("Some valid content that is long enough." * 5, encoding="utf-8")

        _write_queue(queue_path, {
            "00-Inbox/broken-doc.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "skip", "wiki": "pending"},
            }
        })

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.chat.side_effect = LLMResponseError("bad response")

        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            with patch("time.sleep"):
                with pytest.raises(SystemExit) as exc:
                    _mod.main()

        assert exc.value.code == 1
        bad_docs_path = tmp_path / "agents" / "wiki" / "state" / "bad-wiki-docs.txt"
        assert bad_docs_path.exists()
        assert "broken-doc.md" in bad_docs_path.read_text(encoding="utf-8")

    def test_llm_offline_during_batch_aborts_without_bad_doc(self, vault, patch_roots, tmp_path):
        from shared import LLMOfflineError
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)

        doc = tmp_path / "00-Inbox" / "offline-doc.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("Enough content here for processing." * 5, encoding="utf-8")

        _write_queue(queue_path, {
            "00-Inbox/offline-doc.md": {
                "ingestedAt": "2026-06-11T00:00:00Z",
                "type": "document",
                "agents": {"vision": "skip", "lore": "skip", "classification": "skip", "wiki": "pending"},
            }
        })

        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        mock_client.chat.side_effect = LLMOfflineError("offline")

        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            with patch("time.sleep"):
                with pytest.raises(SystemExit) as exc:
                    _mod.main()

        # LLM offline mid-batch → abort, exit 0, do NOT mark file bad
        assert exc.value.code == 0
        bad_docs_path = tmp_path / "agents" / "wiki" / "state" / "bad-wiki-docs.txt"
        if bad_docs_path.exists():
            bad = bad_docs_path.read_text(encoding="utf-8")
            assert "offline-doc.md" not in bad


# ---------------------------------------------------------------------------
# TOOLS list definition
# ---------------------------------------------------------------------------

class TestToolsDefinition:
    def test_required_tools_present(self):
        names = {t["name"] for t in _mod.TOOLS}
        assert "load_canon_context"  in names
        assert "scan_pending"        in names
        assert "synthesize_entity"   in names
        assert "run_batch"           in names

    def test_self_management_tools_included(self):
        names = {t["name"] for t in _mod.TOOLS}
        assert "write_log"            in names
        assert "request_human_review" in names

    def test_all_tools_have_required_keys(self):
        for tool in _mod.TOOLS:
            assert "name"         in tool
            assert "description"  in tool
            assert "input_schema" in tool


# ---------------------------------------------------------------------------
# call_tool dispatch
# ---------------------------------------------------------------------------

class TestCallTool:
    def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            _mod.call_tool("no_such_tool", {}, {"project_root": "/tmp"})

    def test_load_canon_context_returns_count(self, vault, patch_roots):
        result = _mod.call_tool("load_canon_context", {}, {"project_root": str(vault.parent)})
        assert "Canon context loaded" in result

    def test_scan_pending_returns_count(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {})
        result = _mod.call_tool("scan_pending", {}, {"project_root": str(tmp_path)})
        assert "Pending documents" in result

    def test_run_batch_dispatches(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {})
        mock_client = MagicMock()
        mock_client.is_available.return_value = True
        with patch("wiki.tools.compile_wiki.LLMClient", return_value=mock_client):
            result = _mod.call_tool("run_batch", {}, {"project_root": str(tmp_path)})
        assert result is not None

    def test_synthesize_entity_missing_file(self, vault, patch_roots, tmp_path):
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {})
        result = _mod.call_tool(
            "synthesize_entity",
            {"source_path": "00-Inbox/no-such.md"},
            {"project_root": str(tmp_path)},
        )
        assert "ERROR" in result

    def test_synthesize_entity_in_bad_docs(self, vault, patch_roots, tmp_path):
        bad_path = tmp_path / "agents" / "wiki" / "state" / "bad-wiki-docs.txt"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("00-Inbox/bad.md\n", encoding="utf-8")
        queue_path = tmp_path / "system" / "state" / "inbox-queue.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        _write_queue(queue_path, {})
        result = _mod.call_tool(
            "synthesize_entity",
            {"source_path": "00-Inbox/bad.md"},
            {"project_root": str(tmp_path)},
        )
        assert "ERROR" in result
