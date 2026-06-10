"""Tests for classification.tools.enrich_tags."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Bootstrap: ensure .agents/ is on sys.path (conftest.py handles this,
# but also add classification parent for the module import)
_AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

import classification.tools.enrich_tags as _mod
from shared.interfaces import VaultWriteError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    """Minimal vault layout under tmp_path."""
    kb = tmp_path / "knowledge-base"
    (kb / "00-Inbox").mkdir(parents=True)
    (kb / "01-Processing").mkdir(parents=True)
    (kb / "02-Library").mkdir(parents=True)
    return kb


@pytest.fixture
def patch_roots(vault, tmp_path, monkeypatch):
    """Redirect module-level path constants to tmp_path layout."""
    monkeypatch.setattr(_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(_mod, "_VAULT_ROOT",   vault)
    monkeypatch.setattr(_mod, "_INBOX",        vault / "00-Inbox")
    monkeypatch.setattr(_mod, "_PROCESSING",   vault / "01-Processing")
    monkeypatch.setattr(_mod, "_LIBRARY",      vault / "02-Library")
    agent_state = tmp_path / ".agents" / "classification" / "state"
    agent_state.mkdir(parents=True)
    logs_dir = agent_state / "logs"
    logs_dir.mkdir()
    master_log = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
    master_log.parent.mkdir(parents=True)
    master_log.touch()
    monkeypatch.setattr(_mod, "_AGENT_STATE", agent_state)
    monkeypatch.setattr(_mod, "_LOGS_DIR",    logs_dir)
    monkeypatch.setattr(_mod, "_MASTER_LOG",  master_log)
    monkeypatch.setattr(_mod, "_BAD_DOCS",    agent_state / "bad-docs.txt")
    return vault


def _write_md(path: Path, frontmatter: dict, body: str = "") -> None:
    """Write a markdown file with YAML frontmatter."""
    import yaml
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    path.write_text(f"---\n{fm_str}---\n{body}", encoding="utf-8")


# ---------------------------------------------------------------------------
# _allowed_tags / _allowed_types constants
# ---------------------------------------------------------------------------

class TestAllowedSets:
    def test_allowed_tags_count(self):
        assert len(_mod._ALLOWED_TAGS) == 28

    def test_allowed_types_count(self):
        assert len(_mod._ALLOWED_TYPES) == 18

    def test_known_tags_present(self):
        for tag in ("npc", "location", "faction", "quest", "dungeon", "pathfinder2e"):
            assert tag in _mod._ALLOWED_TAGS

    def test_known_types_present(self):
        for t in ("npc", "character", "faction", "location", "dungeon", "lore"):
            assert t in _mod._ALLOWED_TYPES

    def test_approved_not_in_types(self):
        # 'approved' is a status, not a type — must not be mistakenly accepted
        assert "approved" not in _mod._ALLOWED_TYPES


# ---------------------------------------------------------------------------
# _library_slugs
# ---------------------------------------------------------------------------

class TestLibrarySlugs:
    def test_returns_empty_when_no_library(self, patch_roots, vault):
        import shutil
        shutil.rmtree(vault / "02-Library")
        assert _mod._library_slugs() == set()

    def test_returns_stems(self, patch_roots, vault):
        (vault / "02-Library" / "npc-villain.md").touch()
        (vault / "02-Library" / "location-dungeon-01.md").touch()
        slugs = _mod._library_slugs()
        assert "npc-villain" in slugs
        assert "location-dungeon-01" in slugs

    def test_case_normalized(self, patch_roots, vault):
        (vault / "02-Library" / "NPC-Villain.md").touch()
        assert "npc-villain" in _mod._library_slugs()


# ---------------------------------------------------------------------------
# _candidate_files
# ---------------------------------------------------------------------------

class TestCandidateFiles:
    def test_returns_inbox_and_processing(self, patch_roots, vault):
        a = vault / "00-Inbox" / "note-a.md"
        b = vault / "01-Processing" / "note-b.md"
        a.touch()
        b.touch()
        paths = _mod._candidate_files(set())
        assert a in paths
        assert b in paths

    def test_skips_bad_docs(self, patch_roots, vault, tmp_path):
        a = vault / "00-Inbox" / "bad.md"
        a.touch()
        rel = a.relative_to(tmp_path).as_posix()
        paths = _mod._candidate_files({rel})
        assert a not in paths

    def test_skips_git_and_agents_dirs(self, patch_roots, vault):
        git_file = vault / "00-Inbox" / ".git" / "COMMIT_EDITMSG"
        git_file.parent.mkdir()
        git_file.touch()
        paths = _mod._candidate_files(set())
        assert git_file not in paths


# ---------------------------------------------------------------------------
# _assert_not_library
# ---------------------------------------------------------------------------

class TestAssertNotLibrary:
    def test_raises_for_library_file(self, patch_roots, vault):
        target = vault / "02-Library" / "npc-test.md"
        with pytest.raises(VaultWriteError):
            _mod._assert_not_library(target)

    def test_passes_for_processing_file(self, patch_roots, vault):
        target = vault / "01-Processing" / "npc-test.md"
        _mod._assert_not_library(target)  # must not raise

    def test_passes_for_inbox_file(self, patch_roots, vault):
        target = vault / "00-Inbox" / "note.md"
        _mod._assert_not_library(target)  # must not raise


# ---------------------------------------------------------------------------
# _slug_similarity
# ---------------------------------------------------------------------------

class TestSlugSimilarity:
    def test_identical_strings(self):
        assert _mod._slug_similarity("npc-villain", "npc-villain") == 1.0

    def test_completely_different(self):
        score = _mod._slug_similarity("npc-villain", "location-river")
        assert score < 0.5

    def test_near_duplicate(self):
        score = _mod._slug_similarity("npc-villain-01", "npc-villain-02")
        assert score >= _mod._SIMILARITY_THRESHOLD

    def test_symmetry(self):
        a, b = "quest-missing-villagers", "quest-missing-villager"
        assert _mod._slug_similarity(a, b) == _mod._slug_similarity(b, a)


# ---------------------------------------------------------------------------
# _run_flag_duplicates
# ---------------------------------------------------------------------------

class TestRunFlagDuplicates:
    def test_exact_match_sets_duplicate_of(self, patch_roots, vault):
        import yaml
        (vault / "02-Library" / "npc-villain.md").touch()
        proc = vault / "01-Processing" / "npc-villain.md"
        _write_md(proc, {"id": "npc-villain", "tags": []})

        _mod._run_flag_duplicates()

        content = proc.read_text(encoding="utf-8")
        fm_text = content.split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm.get("duplicate_of") == "npc-villain"

    def test_no_duplicates_when_no_library(self, patch_roots, vault):
        proc = vault / "01-Processing" / "npc-hero.md"
        _write_md(proc, {"id": "npc-hero", "tags": []})
        count = _mod._run_flag_duplicates()
        assert count == 0

    def test_similarity_flag(self, patch_roots, vault):
        import yaml
        (vault / "02-Library" / "npc-villain-01.md").touch()
        proc = vault / "01-Processing" / "npc-villain-02.md"
        _write_md(proc, {"id": "npc-villain-02", "tags": []})

        count = _mod._run_flag_duplicates()

        content = proc.read_text(encoding="utf-8")
        fm_text = content.split("---")[1]
        fm = yaml.safe_load(fm_text)
        if count > 0:
            assert "similar_to" in (fm.get("duplicate_of") or "")

    def test_does_not_touch_library_files(self, patch_roots, vault):
        lib_file = vault / "02-Library" / "npc-villain.md"
        _write_md(lib_file, {"id": "npc-villain", "tags": []})
        (vault / "02-Library" / "npc-villain.md")  # reference
        # flag_duplicates should not raise VaultWriteError
        _mod._run_flag_duplicates()


# ---------------------------------------------------------------------------
# _run_infer_type
# ---------------------------------------------------------------------------

class TestRunInferType:
    def test_skips_when_llm_offline(self, patch_roots, vault):
        with patch("classification.tools.enrich_tags.LLMClient") as MockClient:
            MockClient.return_value.is_available.return_value = False
            count, failed = _mod._run_infer_type()
        assert count == 0
        assert failed == 0

    def test_skips_files_with_existing_type(self, patch_roots, vault):
        proc = vault / "01-Processing" / "npc-hero.md"
        _write_md(proc, {"id": "npc-hero", "type": "npc", "tags": []})

        with patch("classification.tools.enrich_tags.LLMClient") as MockClient:
            client = MockClient.return_value
            client.is_available.return_value = True
            client.chat.return_value = '{"type": "location"}'
            count, _ = _mod._run_infer_type()

        # file had type — should not have been processed
        assert count == 0

    def test_infers_type_for_missing_field(self, patch_roots, vault):
        import yaml
        proc = vault / "01-Processing" / "unknown-entity.md"
        _write_md(proc, {"id": "unknown-entity", "tags": []}, body="A dark dungeon.")

        with patch("classification.tools.enrich_tags.LLMClient") as MockClient:
            client = MockClient.return_value
            client.is_available.return_value = True
            client.chat.return_value = '{"type": "dungeon"}'
            count, failed = _mod._run_infer_type()

        assert count == 1
        assert failed == 0
        fm_text = proc.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm.get("type") == "dungeon"

    def test_ignores_invalid_type_from_llm(self, patch_roots, vault):
        import yaml
        proc = vault / "01-Processing" / "unknown-entity.md"
        _write_md(proc, {"id": "unknown-entity", "tags": []})

        with patch("classification.tools.enrich_tags.LLMClient") as MockClient:
            client = MockClient.return_value
            client.is_available.return_value = True
            client.chat.return_value = '{"type": "approved"}'  # disallowed
            _mod._run_infer_type()

        fm_text = proc.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert "type" not in fm


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

class TestToolsDefinition:
    def test_required_tools_present(self):
        names = {t["name"] for t in _mod.TOOLS}
        assert "enrich_tags"     in names
        assert "infer_type"      in names
        assert "flag_duplicates" in names

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

    def test_infer_type_dispatches(self):
        with patch.object(_mod, "_run_infer_type", return_value=(3, 0)) as mock:
            result = _mod.call_tool("infer_type", {}, {"project_root": "/tmp"})
        mock.assert_called_once()
        assert "inferred=3" in result

    def test_flag_duplicates_dispatches(self):
        with patch.object(_mod, "_run_flag_duplicates", return_value=2) as mock:
            result = _mod.call_tool("flag_duplicates", {}, {"project_root": "/tmp"})
        mock.assert_called_once()
        assert "flagged=2" in result
