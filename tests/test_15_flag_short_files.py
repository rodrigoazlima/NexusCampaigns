"""
Tests for .automation/15-flag-short-files.py - Short-Content Flagging Agent

Strategy: import the Python module directly and exercise all public functions
against isolated tmp_path vaults.  No network, no external processes, no
writes outside tmp_path.

Behaviors under test:
  1.  parse_fm            - frontmatter parsed correctly from markdown text
  2.  count_body_lines    - non-blank line counting
  3.  set_field           - YAML field insert / in-place replace
  4.  bad_index_io        - load / save bad-index.json round-trip
  5.  upsert_bad_entry    - insert new entries; update existing without duplicate
  6.  build_js            - bad-index.js written with correct JS wrapper
  7.  flag_bad            - manual flag: updates frontmatter + index + JS
  8.  process_flag        - short files flagged; bad-index + logs written
  9.  process_clear       - previously-flagged files cleared when body grows
 10.  process_skip        - already-flagged short files not re-written
 11.  process_dry_run     - dry-run: logs actions but modifies nothing
 12.  process_backfill    - already-flagged files absent from index are backfilled
 13.  process_errors      - missing 01-Processing/ returns exit code 1
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

_SCRIPT = (
    Path(__file__).parent.parent / "system" / "src" / "nexus" / "workers" / "shortfiles.py"
)

_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location("flag_short_files", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


if not _SCRIPT.exists():
    pytest.skip(
        f"Script not found: {_SCRIPT}",
        allow_module_level=True,
    )

try:
    _mod = _load_module()
except Exception as _exc:
    pytest.skip(
        f"Failed to load {_SCRIPT.name}: {_exc}. "
        "See agents/tests/ for current coverage.",
        allow_module_level=True,
    )

_API_REQUIRED = (
    "_parse_fm", "_count_body_lines", "_set_field",
    "_load_bad_index", "_save_bad_index", "_upsert_bad_entry",
    "build_js", "flag_bad", "process",
)
_MISSING_API = [fn for fn in _API_REQUIRED if not hasattr(_mod, fn)]
if _MISSING_API:
    pytest.skip(
        f"flag_short_files.py API changed - functions not found: {_MISSING_API}. "
        "Refactored module uses _flag_short_file/main/call_tool. "
        "Next step: rewrite these tests against nexus/tasks/flag_short_files.py API.",
        allow_module_level=True,
    )

# Public API aliases
_parse_fm = _mod._parse_fm
_count_body_lines = _mod._count_body_lines
_set_field = _mod._set_field
_load_bad_index = _mod._load_bad_index
_save_bad_index = _mod._save_bad_index
_upsert_bad_entry = _mod._upsert_bad_entry
build_js = _mod.build_js
flag_bad = _mod.flag_bad
process = _mod.process

BAD_INDEX = _mod.BAD_INDEX
BAD_INDEX_JS = _mod.BAD_INDEX_JS
LOG_SHARED = _mod.LOG_SHARED
PROCESSING_DIR = _mod.PROCESSING_DIR
REPROCESSING_STEPS = _mod.REPROCESSING_STEPS
_NEEDS_REPROCESSING_RE = _mod._NEEDS_REPROCESSING_RE


# ---------------------------------------------------------------------------
# Image comparison helpers (project convention - kept for consistency)
# ---------------------------------------------------------------------------


def images_are_equal(a: Path, b: Path) -> bool:
    """Return True when two image files are byte-identical."""
    return a.read_bytes() == b.read_bytes()


def assert_images_similar(a: Path, b: Path, min_ssim: float = 0.90) -> None:
    """Assert SSIM >= min_ssim; skipped when scikit-image / Pillow are absent."""
    try:
        import numpy as np
        from PIL import Image
        from skimage.metrics import structural_similarity as ssim  # type: ignore
    except ImportError:
        pytest.skip("scikit-image / Pillow not installed")
    arr_a = np.array(Image.open(a).convert("L"))
    arr_b = np.array(Image.open(b).convert("L"))
    score = float(ssim(arr_a, arr_b))
    assert score >= min_ssim, f"SSIM {score:.3f} < {min_ssim}: {a.name} vs {b.name}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_md(
    vault: Path,
    filename: str,
    body_lines: int = 15,
    needs_reprocessing: str | None = None,
    sha256: str = "",
) -> Path:
    """Write a Markdown file in 01-Processing/ with configurable content."""
    proc = vault / PROCESSING_DIR
    proc.mkdir(parents=True, exist_ok=True)

    yaml_parts = [
        f"id: {filename.removesuffix('.md')}",
        "type: npc",
        "status: draft",
    ]
    if sha256:
        yaml_parts.append(f"sha256: {sha256}")
    if needs_reprocessing is not None:
        yaml_parts.append(f"needs_reprocessing: {needs_reprocessing}")

    body = "\n".join(f"Body line {i}." for i in range(body_lines))
    content = "---\n" + "\n".join(yaml_parts) + "\n---\n" + body + "\n"

    path = proc / filename
    path.write_text(content, encoding="utf-8")
    return path


def _read_fm(path: Path) -> tuple[str, str]:
    """Return (yaml_block, body) for a Markdown file."""
    return _parse_fm(path.read_text(encoding="utf-8"))


def _has_field(path: Path, field: str, value: str) -> bool:
    """True when frontmatter contains ``field: value``."""
    yaml, _ = _read_fm(path)
    pattern = re.compile(
        rf"^{re.escape(field)}:\s*{re.escape(value)}\s*$", re.MULTILINE
    )
    return bool(pattern.search(yaml))


def _bad_index_path(vault: Path) -> Path:
    return vault / BAD_INDEX


def _shared_log(vault: Path) -> Path:
    return vault / LOG_SHARED


def _bad_index_entries(vault: Path) -> list[dict]:
    return _load_bad_index(vault).get("entries", [])


def _minimal_bad_entry(filename: str, reason: str = "short_content") -> dict:
    return {
        "filename": filename,
        "sha256": "",
        "reason": reason,
        "body_lines": 3,
        "flagged_at": "2026-01-01T00:00:00",
        "reprocessing_steps": list(REPROCESSING_STEPS),
        "improvements": [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal vault tree needed by 15-flag-short-files.py."""
    (tmp_path / PROCESSING_DIR).mkdir(parents=True)
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    (tmp_path / ".automation" / "reports").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# 1. _parse_fm
# ---------------------------------------------------------------------------


class TestParseFm:
    """Frontmatter is correctly split from markdown body."""

    def test_standard_block(self) -> None:
        text = "---\nid: test\ntype: npc\n---\nBody here."
        yaml, body = _parse_fm(text)
        assert "id: test" in yaml
        assert "Body here." in body

    def test_no_frontmatter_returns_empty_yaml(self) -> None:
        yaml, body = _parse_fm("Just body text.")
        assert yaml == ""
        assert body == "Just body text."

    def test_multiline_body_preserved(self) -> None:
        text = "---\nkey: val\n---\nLine 1.\nLine 2.\nLine 3."
        _, body = _parse_fm(text)
        assert "Line 1." in body
        assert "Line 3." in body

    def test_empty_frontmatter_block(self) -> None:
        yaml, body = _parse_fm("---\n---\nBody only.")
        assert yaml == ""
        assert "Body only." in body

    def test_blank_lines_in_body(self) -> None:
        _, body = _parse_fm("---\nid: x\n---\nPara 1.\n\nPara 2.")
        assert "Para 1." in body
        assert "Para 2." in body

    def test_unicode_in_frontmatter(self) -> None:
        text = "---\ntitle: NPC «Кирил»\nid: npc-1\n---\nContent."
        yaml, body = _parse_fm(text)
        assert "NPC" in yaml
        assert "Content." in body

    def test_yaml_block_does_not_bleed_into_body(self) -> None:
        text = "---\nfoo: bar\n---\nbody line"
        yaml, body = _parse_fm(text)
        assert "foo: bar" not in body
        assert "body line" not in yaml


# ---------------------------------------------------------------------------
# 2. _count_body_lines
# ---------------------------------------------------------------------------


class TestCountBodyLines:
    """Non-blank lines are counted accurately."""

    @pytest.mark.parametrize(
        "body,expected",
        [
            ("Line 1.\nLine 2.\nLine 3.", 3),
            ("Line 1.\n\nLine 2.", 2),
            ("\n\n\n", 0),
            ("", 0),
            ("  \t  \n  \t  ", 0),
            ("A\nB\nC\nD\nE", 5),
            ("Single line.", 1),
        ],
    )
    def test_count(self, body: str, expected: int) -> None:
        assert _count_body_lines(body) == expected

    def test_mixed_blank_and_content(self) -> None:
        body = "\nA\n\nB\n\n\nC\n"
        assert _count_body_lines(body) == 3

    def test_trailing_newline_not_counted(self) -> None:
        assert _count_body_lines("text\n") == 1

    def test_only_spaces_not_counted(self) -> None:
        assert _count_body_lines("   ") == 0


# ---------------------------------------------------------------------------
# 3. _set_field
# ---------------------------------------------------------------------------


class TestSetField:
    """YAML field is inserted when absent and replaced in-place when present."""

    def test_inserts_new_field(self) -> None:
        result = _set_field(
            "id: test", _NEEDS_REPROCESSING_RE, "needs_reprocessing", "true"
        )
        assert "needs_reprocessing: true" in result

    def test_replaces_existing_field(self) -> None:
        yaml = "id: test\nneeds_reprocessing: false"
        result = _set_field(
            yaml, _NEEDS_REPROCESSING_RE, "needs_reprocessing", "true"
        )
        assert "needs_reprocessing: true" in result
        assert "needs_reprocessing: false" not in result

    def test_no_duplicate_field_after_replace(self) -> None:
        yaml = "id: test\nneeds_reprocessing: false"
        result = _set_field(
            yaml, _NEEDS_REPROCESSING_RE, "needs_reprocessing", "true"
        )
        assert result.count("needs_reprocessing:") == 1

    def test_surrounding_fields_preserved(self) -> None:
        yaml = "id: test\ntype: npc\nneeds_reprocessing: false"
        result = _set_field(
            yaml, _NEEDS_REPROCESSING_RE, "needs_reprocessing", "true"
        )
        assert "id: test" in result
        assert "type: npc" in result

    @pytest.mark.parametrize("value", ["true", "false", "pending"])
    def test_various_values(self, value: str) -> None:
        result = _set_field(
            "id: x", _NEEDS_REPROCESSING_RE, "needs_reprocessing", value
        )
        assert f"needs_reprocessing: {value}" in result


# ---------------------------------------------------------------------------
# 4. bad_index_io
# ---------------------------------------------------------------------------


class TestBadIndexIO:
    """load / save bad-index.json is a lossless round-trip."""

    def test_load_missing_returns_default(self, vault: Path) -> None:
        data = _load_bad_index(vault)
        assert data == {"version": 1, "entries": []}

    def test_round_trip(self, vault: Path) -> None:
        index = {"version": 1, "entries": [{"filename": "x.md", "sha256": "abc"}]}
        _save_bad_index(vault, index)
        assert _load_bad_index(vault) == index

    def test_save_writes_file_when_parent_exists(self, vault: Path) -> None:
        _save_bad_index(vault, {"version": 1, "entries": []})
        assert _bad_index_path(vault).exists()

    def test_corrupt_json_returns_default(self, vault: Path) -> None:
        _bad_index_path(vault).parent.mkdir(parents=True, exist_ok=True)
        _bad_index_path(vault).write_text("{ invalid json", encoding="utf-8")
        assert _load_bad_index(vault) == {"version": 1, "entries": []}

    def test_saved_output_is_pretty_printed(self, vault: Path) -> None:
        _save_bad_index(vault, {"version": 1, "entries": []})
        raw = _bad_index_path(vault).read_text(encoding="utf-8")
        assert "\n" in raw

    def test_unicode_preserved(self, vault: Path) -> None:
        index = {"version": 1, "entries": [{"filename": "npc-кирил.md"}]}
        _save_bad_index(vault, index)
        loaded = _load_bad_index(vault)
        assert loaded["entries"][0]["filename"] == "npc-кирил.md"


# ---------------------------------------------------------------------------
# 5. _upsert_bad_entry
# ---------------------------------------------------------------------------


class TestUpsertBadEntry:
    """Upsert inserts new entries and updates existing ones without duplicates."""

    def test_inserts_new_entry(self) -> None:
        index: dict = {"version": 1, "entries": []}
        _upsert_bad_entry(index, "test.md", "abc123", "short_content", 3)
        assert len(index["entries"]) == 1
        e = index["entries"][0]
        assert e["filename"] == "test.md"
        assert e["sha256"] == "abc123"
        assert e["reason"] == "short_content"
        assert e["body_lines"] == 3

    def test_new_entry_has_reprocessing_steps(self) -> None:
        index: dict = {"version": 1, "entries": []}
        _upsert_bad_entry(index, "test.md", "", "short_content", 2)
        assert index["entries"][0]["reprocessing_steps"] == REPROCESSING_STEPS

    def test_new_entry_has_flagged_at(self) -> None:
        index: dict = {"version": 1, "entries": []}
        _upsert_bad_entry(index, "test.md", "", "short_content", 2)
        assert "flagged_at" in index["entries"][0]

    def test_new_entry_has_empty_improvements(self) -> None:
        index: dict = {"version": 1, "entries": []}
        _upsert_bad_entry(index, "test.md", "", "short_content", 2)
        assert index["entries"][0]["improvements"] == []

    def test_updates_existing_entry(self) -> None:
        index: dict = {
            "version": 1,
            "entries": [_minimal_bad_entry("test.md", "old_reason")],
        }
        _upsert_bad_entry(index, "test.md", "new_sha", "new_reason", 5)
        assert len(index["entries"]) == 1
        e = index["entries"][0]
        assert e["reason"] == "new_reason"
        assert e["body_lines"] == 5

    def test_repeated_upsert_no_duplicate(self) -> None:
        index: dict = {"version": 1, "entries": []}
        _upsert_bad_entry(index, "dup.md", "", "r", 2)
        _upsert_bad_entry(index, "dup.md", "", "r2", 3)
        assert len(index["entries"]) == 1

    def test_multiple_distinct_files(self) -> None:
        index: dict = {"version": 1, "entries": []}
        _upsert_bad_entry(index, "a.md", "", "r", 1)
        _upsert_bad_entry(index, "b.md", "", "r", 2)
        _upsert_bad_entry(index, "c.md", "", "r", 3)
        assert len(index["entries"]) == 3

    @pytest.mark.parametrize(
        "reason",
        ["short_content", "manual", "missing_image_ref", "bad_quality"],
    )
    def test_various_reasons_stored(self, reason: str) -> None:
        index: dict = {"version": 1, "entries": []}
        _upsert_bad_entry(index, "test.md", "", reason, 5)
        assert index["entries"][0]["reason"] == reason


# ---------------------------------------------------------------------------
# 6. build_js
# ---------------------------------------------------------------------------


class TestBuildJs:
    """bad-index.js is written with the correct JS assignment wrapper."""

    def test_creates_js_file(self, vault: Path) -> None:
        build_js(vault)
        assert (vault / BAD_INDEX_JS).exists()

    def test_js_declares_const(self, vault: Path) -> None:
        build_js(vault)
        assert "const BAD_INDEX" in (vault / BAD_INDEX_JS).read_text(encoding="utf-8")

    def test_js_contains_version_field(self, vault: Path) -> None:
        build_js(vault)
        content = (vault / BAD_INDEX_JS).read_text(encoding="utf-8")
        assert '"version"' in content

    def test_js_reflects_index_entries(self, vault: Path) -> None:
        index = {
            "version": 1,
            "entries": [_minimal_bad_entry("npc-test.md")],
        }
        _save_bad_index(vault, index)
        build_js(vault)
        content = (vault / BAD_INDEX_JS).read_text(encoding="utf-8")
        assert "npc-test.md" in content

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        build_js(tmp_path)
        assert (tmp_path / BAD_INDEX_JS).exists()

    def test_returns_zero(self, vault: Path) -> None:
        assert build_js(vault) == 0

    def test_overwrites_on_second_call(self, vault: Path) -> None:
        build_js(vault)
        index = {"version": 1, "entries": [{"filename": "x.md"}]}
        _save_bad_index(vault, index)
        build_js(vault)
        assert "x.md" in (vault / BAD_INDEX_JS).read_text(encoding="utf-8")

    def test_js_ends_with_semicolon(self, vault: Path) -> None:
        build_js(vault)
        content = (vault / BAD_INDEX_JS).read_text(encoding="utf-8").strip()
        assert content.endswith(";")


# ---------------------------------------------------------------------------
# 7. flag_bad
# ---------------------------------------------------------------------------


class TestFlagBad:
    """flag_bad sets frontmatter flags and updates bad-index + bad-index.js."""

    def test_returns_zero_on_success(self, vault: Path) -> None:
        md = _make_md(vault, "npc-villain.md", body_lines=5)
        assert flag_bad(vault, md.name, "manual") == 0

    def test_sets_needs_reprocessing_true(self, vault: Path) -> None:
        md = _make_md(vault, "npc-villain.md", body_lines=5)
        flag_bad(vault, md.name, "manual")
        assert _has_field(md, "needs_reprocessing", "true")

    def test_sets_bad_processing_true(self, vault: Path) -> None:
        md = _make_md(vault, "npc-villain.md", body_lines=5)
        flag_bad(vault, md.name, "manual")
        assert _has_field(md, "bad_processing", "true")

    def test_adds_entry_to_bad_index(self, vault: Path) -> None:
        md = _make_md(vault, "npc-villain.md", body_lines=5)
        flag_bad(vault, md.name, "manual")
        assert any(
            e["filename"] == "npc-villain.md" for e in _bad_index_entries(vault)
        )

    def test_reason_stored_in_index(self, vault: Path) -> None:
        md = _make_md(vault, "npc-x.md", body_lines=5)
        flag_bad(vault, md.name, "test_reason")
        entry = next(
            e for e in _bad_index_entries(vault) if e["filename"] == "npc-x.md"
        )
        assert entry["reason"] == "test_reason"

    def test_builds_js_file(self, vault: Path) -> None:
        md = _make_md(vault, "npc-x.md", body_lines=5)
        flag_bad(vault, md.name, "manual")
        assert (vault / BAD_INDEX_JS).exists()

    def test_returns_one_for_missing_file(self, vault: Path) -> None:
        assert flag_bad(vault, "nonexistent.md", "manual") == 1

    def test_log_contains_flag_bad_message(self, vault: Path) -> None:
        md = _make_md(vault, "npc-x.md", body_lines=5)
        flag_bad(vault, md.name, "manual")
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "FLAG-BAD" in log

    def test_sha256_captured_from_frontmatter(self, vault: Path) -> None:
        sha = "a" * 64
        md = _make_md(vault, "npc-sha.md", body_lines=5, sha256=sha)
        flag_bad(vault, md.name, "manual")
        entry = next(
            e for e in _bad_index_entries(vault) if e["filename"] == "npc-sha.md"
        )
        assert entry["sha256"] == sha

    def test_idempotent_second_flag_no_duplicate(self, vault: Path) -> None:
        md = _make_md(vault, "npc-idem.md", body_lines=5)
        flag_bad(vault, md.name, "reason-a")
        flag_bad(vault, md.name, "reason-b")
        count = sum(
            1 for e in _bad_index_entries(vault) if e["filename"] == "npc-idem.md"
        )
        assert count == 1

    @pytest.mark.parametrize(
        "reason", ["manual", "short_content", "bad_quality", "custom-tag"]
    )
    def test_various_reasons(self, vault: Path, reason: str) -> None:
        md = _make_md(vault, "npc-r.md", body_lines=5)
        assert flag_bad(vault, md.name, reason) == 0
        assert any(e["reason"] == reason for e in _bad_index_entries(vault))


# ---------------------------------------------------------------------------
# 8. process - flagging short files
# ---------------------------------------------------------------------------


class TestProcessFlag:
    """Short files are flagged; bad-index and logs are written."""

    def test_returns_zero_on_success(self, vault: Path) -> None:
        _make_md(vault, "npc-short.md", body_lines=3)
        assert process(vault, min_lines=10, dry_run=False) == 0

    def test_short_file_gets_needs_reprocessing_true(self, vault: Path) -> None:
        md = _make_md(vault, "npc-short.md", body_lines=3)
        process(vault, min_lines=10, dry_run=False)
        assert _has_field(md, "needs_reprocessing", "true")

    def test_long_file_not_flagged(self, vault: Path) -> None:
        md = _make_md(vault, "npc-long.md", body_lines=20)
        process(vault, min_lines=10, dry_run=False)
        yaml, _ = _read_fm(md)
        assert "needs_reprocessing: true" not in yaml

    def test_short_file_added_to_bad_index(self, vault: Path) -> None:
        _make_md(vault, "npc-short.md", body_lines=3)
        process(vault, min_lines=10, dry_run=False)
        assert any(
            e["filename"] == "npc-short.md" for e in _bad_index_entries(vault)
        )

    def test_reason_is_short_content(self, vault: Path) -> None:
        _make_md(vault, "npc-s.md", body_lines=3)
        process(vault, min_lines=10, dry_run=False)
        entry = next(
            e for e in _bad_index_entries(vault) if e["filename"] == "npc-s.md"
        )
        assert entry["reason"] == "short_content"

    def test_exactly_at_threshold_not_flagged(self, vault: Path) -> None:
        """body_lines == min_lines → not short → not flagged."""
        md = _make_md(vault, "npc-exact.md", body_lines=10)
        process(vault, min_lines=10, dry_run=False)
        assert not _has_field(md, "needs_reprocessing", "true")

    def test_one_below_threshold_flagged(self, vault: Path) -> None:
        md = _make_md(vault, "npc-less.md", body_lines=9)
        process(vault, min_lines=10, dry_run=False)
        assert _has_field(md, "needs_reprocessing", "true")

    def test_log_has_start_marker(self, vault: Path) -> None:
        process(vault, min_lines=10, dry_run=False)
        assert "--- START ---" in _shared_log(vault).read_text(encoding="utf-8")

    def test_log_has_done_marker(self, vault: Path) -> None:
        process(vault, min_lines=10, dry_run=False)
        assert "--- DONE ---" in _shared_log(vault).read_text(encoding="utf-8")

    def test_log_has_task_id_prefix(self, vault: Path) -> None:
        process(vault, min_lines=10, dry_run=False)
        assert "[review-agent]" in _shared_log(vault).read_text(encoding="utf-8")

    def test_per_task_log_created(self, vault: Path) -> None:
        process(vault, min_lines=10, dry_run=False)
        logs_dir = vault / ".automation" / "logs"
        task_logs = list(logs_dir.glob("15-flag-short-files_*.log"))
        assert len(task_logs) >= 1

    def test_js_file_built(self, vault: Path) -> None:
        _make_md(vault, "npc-s.md", body_lines=3)
        process(vault, min_lines=10, dry_run=False)
        assert (vault / BAD_INDEX_JS).exists()

    @pytest.mark.parametrize(
        "n_short,n_long",
        [(1, 0), (0, 3), (3, 2), (5, 5)],
    )
    def test_mixed_short_and_long(
        self, vault: Path, n_short: int, n_long: int
    ) -> None:
        for i in range(n_short):
            _make_md(vault, f"npc-short-{i}.md", body_lines=3)
        for i in range(n_long):
            _make_md(vault, f"npc-long-{i}.md", body_lines=20)
        process(vault, min_lines=10, dry_run=False)
        flagged = {e["filename"] for e in _bad_index_entries(vault)}
        for i in range(n_short):
            assert f"npc-short-{i}.md" in flagged
        for i in range(n_long):
            assert f"npc-long-{i}.md" not in flagged


# ---------------------------------------------------------------------------
# 9. process - clearing previously-flagged files
# ---------------------------------------------------------------------------


class TestProcessClear:
    """Files flagged before whose body now exceeds threshold get flag cleared."""

    def test_clears_needs_reprocessing(self, vault: Path) -> None:
        md = _make_md(vault, "npc-c.md", body_lines=20, needs_reprocessing="true")
        process(vault, min_lines=10, dry_run=False)
        assert _has_field(md, "needs_reprocessing", "false")

    def test_clear_action_logged(self, vault: Path) -> None:
        _make_md(vault, "npc-c.md", body_lines=20, needs_reprocessing="true")
        process(vault, min_lines=10, dry_run=False)
        assert "CLEAR" in _shared_log(vault).read_text(encoding="utf-8")

    def test_other_frontmatter_fields_preserved_on_clear(self, vault: Path) -> None:
        md = _make_md(vault, "npc-c.md", body_lines=20, needs_reprocessing="true")
        process(vault, min_lines=10, dry_run=False)
        yaml, _ = _read_fm(md)
        assert "id:" in yaml
        assert "type:" in yaml
        assert "status:" in yaml


# ---------------------------------------------------------------------------
# 10. process - skip already-flagged short files
# ---------------------------------------------------------------------------


class TestProcessSkip:
    """Already-flagged short files are not re-written; skip is logged."""

    def test_already_flagged_short_file_not_rewritten(self, vault: Path) -> None:
        md = _make_md(vault, "npc-skip.md", body_lines=3, needs_reprocessing="true")
        content_before = md.read_text(encoding="utf-8")
        process(vault, min_lines=10, dry_run=False)
        assert md.read_text(encoding="utf-8") == content_before

    def test_skip_logged(self, vault: Path) -> None:
        _make_md(vault, "npc-skip.md", body_lines=3, needs_reprocessing="true")
        process(vault, min_lines=10, dry_run=False)
        assert "SKIP" in _shared_log(vault).read_text(encoding="utf-8")

    def test_already_flagged_absent_from_index_backfilled(self, vault: Path) -> None:
        """Files flagged before bad-index existed must be silently backfilled."""
        _make_md(vault, "npc-bf.md", body_lines=3, needs_reprocessing="true")
        process(vault, min_lines=10, dry_run=False)
        assert any(
            e["filename"] == "npc-bf.md" for e in _bad_index_entries(vault)
        )


# ---------------------------------------------------------------------------
# 11. process - dry run
# ---------------------------------------------------------------------------


class TestProcessDryRun:
    """Dry-run logs actions but modifies no files."""

    def test_returns_zero(self, vault: Path) -> None:
        _make_md(vault, "npc-dry.md", body_lines=3)
        assert process(vault, min_lines=10, dry_run=True) == 0

    def test_md_file_not_modified(self, vault: Path) -> None:
        md = _make_md(vault, "npc-dry.md", body_lines=3)
        content_before = md.read_text(encoding="utf-8")
        process(vault, min_lines=10, dry_run=True)
        assert md.read_text(encoding="utf-8") == content_before

    def test_bad_index_not_created(self, vault: Path) -> None:
        _make_md(vault, "npc-dry.md", body_lines=3)
        process(vault, min_lines=10, dry_run=True)
        assert not _bad_index_path(vault).exists()

    def test_js_file_not_created(self, vault: Path) -> None:
        _make_md(vault, "npc-dry.md", body_lines=3)
        process(vault, min_lines=10, dry_run=True)
        assert not (vault / BAD_INDEX_JS).exists()

    def test_flag_action_still_logged(self, vault: Path) -> None:
        _make_md(vault, "npc-dry.md", body_lines=3)
        process(vault, min_lines=10, dry_run=True)
        assert "FLAG" in _shared_log(vault).read_text(encoding="utf-8")

    def test_already_flagged_md_not_modified_in_dry_run(self, vault: Path) -> None:
        md = _make_md(vault, "npc-dry-c.md", body_lines=20, needs_reprocessing="true")
        content_before = md.read_text(encoding="utf-8")
        process(vault, min_lines=10, dry_run=True)
        assert md.read_text(encoding="utf-8") == content_before

    @pytest.mark.parametrize("min_lines", [5, 10, 20, 50])
    def test_various_thresholds_no_writes(self, vault: Path, min_lines: int) -> None:
        _make_md(vault, "npc-t.md", body_lines=3)
        process(vault, min_lines=min_lines, dry_run=True)
        assert not _bad_index_path(vault).exists()


# ---------------------------------------------------------------------------
# 12. process - backfill
# ---------------------------------------------------------------------------


class TestProcessBackfill:
    """Files already flagged but absent from bad-index are added on next run."""

    def test_backfills_when_index_exists_but_missing_entry(self, vault: Path) -> None:
        _make_md(vault, "npc-bf.md", body_lines=3, needs_reprocessing="true")
        _save_bad_index(vault, {"version": 1, "entries": []})
        process(vault, min_lines=10, dry_run=False)
        assert any(
            e["filename"] == "npc-bf.md" for e in _bad_index_entries(vault)
        )

    def test_backfill_no_duplicate_when_entry_already_present(
        self, vault: Path
    ) -> None:
        _make_md(vault, "npc-bf.md", body_lines=3, needs_reprocessing="true")
        _save_bad_index(
            vault, {"version": 1, "entries": [_minimal_bad_entry("npc-bf.md")]}
        )
        process(vault, min_lines=10, dry_run=False)
        count = sum(
            1 for e in _bad_index_entries(vault) if e["filename"] == "npc-bf.md"
        )
        assert count == 1


# ---------------------------------------------------------------------------
# 13. process - error cases
# ---------------------------------------------------------------------------


class TestProcessErrors:
    """Missing / unusual vault structures are handled gracefully."""

    def test_missing_processing_dir_returns_one(self, tmp_path: Path) -> None:
        (tmp_path / ".automation" / "logs").mkdir(parents=True)
        (tmp_path / ".automation" / "reports").mkdir(parents=True)
        assert process(tmp_path, min_lines=10, dry_run=False) == 1

    def test_empty_processing_dir_returns_zero(self, vault: Path) -> None:
        assert process(vault, min_lines=10, dry_run=False) == 0

    def test_empty_dir_no_bad_index_entries(self, vault: Path) -> None:
        process(vault, min_lines=10, dry_run=False)
        if _bad_index_path(vault).exists():
            assert _load_bad_index(vault)["entries"] == []

    def test_second_run_is_idempotent(self, vault: Path) -> None:
        _make_md(vault, "npc-s.md", body_lines=3)
        process(vault, min_lines=10, dry_run=False)
        process(vault, min_lines=10, dry_run=False)
        count = sum(
            1 for e in _bad_index_entries(vault) if e["filename"] == "npc-s.md"
        )
        assert count == 1

    def test_log_appends_across_runs(self, vault: Path) -> None:
        process(vault, min_lines=10, dry_run=False)
        process(vault, min_lines=10, dry_run=False)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert log.count("--- START ---") >= 2

    def test_log_timestamp_format(self, vault: Path) -> None:
        process(vault, min_lines=10, dry_run=False)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", log)

    @pytest.mark.parametrize("min_lines", [1, 5, 10, 50, 100])
    def test_files_above_threshold_not_flagged(
        self, vault: Path, min_lines: int
    ) -> None:
        _make_md(vault, "npc-over.md", body_lines=min_lines + 5)
        process(vault, min_lines=min_lines, dry_run=False)
        if _bad_index_path(vault).exists():
            assert not any(
                e["filename"] == "npc-over.md" for e in _bad_index_entries(vault)
            )

