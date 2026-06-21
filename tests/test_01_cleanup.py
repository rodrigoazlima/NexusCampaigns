"""
Tests for .automation/legacy/01-cleanup.ps1

Strategy: patch $VaultRoot in script text, write to tmp_path, invoke via
subprocess. No image processing -- this script manipulates .md files.

Behaviors under test:
  1. Duplicate removal   -- delete "* 1.md" when base ".md" exists
  2. Filename repair     -- strip leading ^[^A-Za-z0-9]+ from Clippings filenames
  3. TODO.md migration   -- move TODO.md -> RAW/SKILLS/YouTube Learning Channels.md
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    Path(__file__).parent.parent / ".automation" / "legacy" / "01-cleanup.ps1"
)
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

# Prefer pwsh (PS 7+); fall back to built-in powershell.exe (PS 5.1)
_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_cleanup(vault_root: Path) -> subprocess.CompletedProcess[str]:
    """
    Patch $VaultRoot in the script, write to tmp, execute via PowerShell.

    Returns CompletedProcess so callers can inspect stdout/stderr/returncode.
    """
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    patched = script_text.replace(
        f"$VaultRoot = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot = '{vault_root}'",
    )
    temp_script = vault_root / "_test-cleanup.ps1"
    temp_script.write_text(patched, encoding="utf-8")

    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(temp_script)],
        capture_output=True,
        text=True,
        timeout=30,
    )


# Mirrors the PowerShell regex: ^[^A-Za-z0-9]+(.+)$
_LEADING_NONALNUM = re.compile(r"^[^A-Za-z0-9]+(.+)$")


def expected_repaired_name(filename: str) -> str:
    """Return the post-repair filename using the same regex as the PS1 script."""
    m = _LEADING_NONALNUM.match(filename)
    return m.group(1) if m else filename


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Generator[Path, None, None]:
    """Minimal vault directory tree required by the script."""
    (tmp_path / "Clippings").mkdir()
    (tmp_path / "RAW" / "SKILLS").mkdir(parents=True)
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    yield tmp_path


# ---------------------------------------------------------------------------
# 1. Duplicate removal
# ---------------------------------------------------------------------------


class TestDuplicateRemoval:
    """'* 1.md' files deleted when the corresponding base '.md' exists."""

    def test_removes_dupe_when_base_exists(self, vault: Path) -> None:
        """Dupe deleted; base preserved with original content."""
        clippings = vault / "Clippings"
        (clippings / "notes.md").write_text("original", encoding="utf-8")
        (clippings / "notes 1.md").write_text("duplicate", encoding="utf-8")

        run_cleanup(vault)

        assert (clippings / "notes.md").exists()
        assert not (clippings / "notes 1.md").exists()
        assert (clippings / "notes.md").read_text(encoding="utf-8") == "original"

    def test_keeps_dupe_when_no_base(self, vault: Path) -> None:
        """'* 1.md' file preserved when no corresponding base exists."""
        dupe = vault / "Clippings" / "orphan 1.md"
        dupe.write_text("only copy", encoding="utf-8")

        run_cleanup(vault)

        assert dupe.exists()

    @pytest.mark.parametrize(
        "base_name,dupe_name",
        [
            ("article.md", "article 1.md"),
            ("My Note.md", "My Note 1.md"),
            ("a b c.md", "a b c 1.md"),
        ],
    )
    def test_removes_varied_patterns(
        self, vault: Path, base_name: str, dupe_name: str
    ) -> None:
        """Duplicate removal works for varied filename patterns."""
        clippings = vault / "Clippings"
        (clippings / base_name).write_text("base", encoding="utf-8")
        (clippings / dupe_name).write_text("dupe", encoding="utf-8")

        run_cleanup(vault)

        assert (clippings / base_name).exists()
        assert not (clippings / dupe_name).exists()

    def test_removes_multiple_dupes(self, vault: Path) -> None:
        """All dupes removed when multiple base/dupe pairs exist."""
        clippings = vault / "Clippings"
        pairs = [("alpha.md", "alpha 1.md"), ("beta.md", "beta 1.md")]
        for base_name, dupe_name in pairs:
            (clippings / base_name).write_text("base", encoding="utf-8")
            (clippings / dupe_name).write_text("dupe", encoding="utf-8")

        run_cleanup(vault)

        for base_name, dupe_name in pairs:
            assert (clippings / base_name).exists()
            assert not (clippings / dupe_name).exists()

    def test_empty_clippings_exits_cleanly(self, vault: Path) -> None:
        """Empty Clippings directory: exit code 0, no crash."""
        result = run_cleanup(vault)
        assert result.returncode == 0

    def test_missing_clippings_exits_cleanly(self, vault: Path) -> None:
        """Missing Clippings directory handled via -ErrorAction SilentlyContinue."""
        (vault / "Clippings").rmdir()
        result = run_cleanup(vault)
        assert result.returncode == 0

    def test_non_dupe_md_not_deleted(self, vault: Path) -> None:
        """Normal .md files (no '* 1.md' pattern) are untouched."""
        clippings = vault / "Clippings"
        normal = clippings / "regular.md"
        normal.write_text("keep me", encoding="utf-8")

        run_cleanup(vault)

        assert normal.exists()
        assert normal.read_text(encoding="utf-8") == "keep me"


# ---------------------------------------------------------------------------
# 2. Malformed filename repair
# ---------------------------------------------------------------------------


class TestMalformedFilenameRepair:
    """Strip leading ^[^A-Za-z0-9]+ chars from filenames in Clippings/."""

    @pytest.mark.parametrize(
        "bad_name",
        [
            "!note.md",
            "-article.md",
            "###heading.md",
            " leading-space.md",
            "...dots.md",
            "!@#$start.md",
        ],
    )
    def test_strips_leading_non_alphanumeric(self, vault: Path, bad_name: str) -> None:
        """Files with leading non-alphanumeric chars renamed to stripped form."""
        clippings = vault / "Clippings"
        (clippings / bad_name).write_text("content", encoding="utf-8")
        expected = expected_repaired_name(bad_name)

        run_cleanup(vault)

        assert (clippings / expected).exists(), (
            f"Expected renamed file '{expected}' not found"
        )
        assert not (clippings / bad_name).exists(), (
            f"Malformed file '{bad_name}' should be gone"
        )

    def test_clean_filename_unchanged(self, vault: Path) -> None:
        """Files with alphanumeric-start names are not touched."""
        clippings = vault / "Clippings"
        name = "clean-note.md"
        (clippings / name).write_text("content", encoding="utf-8")

        run_cleanup(vault)

        assert (clippings / name).exists()

    def test_digit_start_unchanged(self, vault: Path) -> None:
        """Files starting with a digit are not renamed (digits are alphanumeric)."""
        clippings = vault / "Clippings"
        name = "1note.md"
        (clippings / name).write_text("content", encoding="utf-8")

        run_cleanup(vault)

        assert (clippings / name).exists()

    def test_rename_skipped_when_target_exists(self, vault: Path) -> None:
        """Malformed file not renamed if clean target already exists; both survive."""
        clippings = vault / "Clippings"
        (clippings / "!note.md").write_text("bad", encoding="utf-8")
        (clippings / "note.md").write_text("existing", encoding="utf-8")

        run_cleanup(vault)

        assert (clippings / "!note.md").exists(), "Bad file must survive when target exists"
        assert (clippings / "note.md").exists()
        assert (clippings / "note.md").read_text(encoding="utf-8") == "existing"

    def test_file_content_preserved_after_rename(self, vault: Path) -> None:
        """Content of renamed file is preserved byte-for-byte."""
        clippings = vault / "Clippings"
        content = "# My Article\n\nBody text here."
        (clippings / "!my-article.md").write_text(content, encoding="utf-8")

        run_cleanup(vault)

        renamed = clippings / "my-article.md"
        assert renamed.exists()
        assert renamed.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# 3. TODO.md migration
# ---------------------------------------------------------------------------

TARGET_REL = Path("RAW") / "SKILLS" / "YouTube Learning Channels.md"


class TestTodoMigration:
    """TODO.md -> RAW/SKILLS/YouTube Learning Channels.md migration."""

    def test_moves_todo_when_target_absent(self, vault: Path) -> None:
        """TODO.md moved; content preserved; original path gone."""
        todo = vault / "TODO.md"
        todo.write_text("# My TODOs\n- item 1", encoding="utf-8")
        target = vault / TARGET_REL

        run_cleanup(vault)

        assert not todo.exists(), "TODO.md must be removed from vault root"
        assert target.exists(), "Target file must be created"
        assert target.read_text(encoding="utf-8") == "# My TODOs\n- item 1"

    def test_skips_move_when_target_exists(self, vault: Path) -> None:
        """TODO.md left in place when target already exists; target not overwritten."""
        todo = vault / "TODO.md"
        todo.write_text("new content", encoding="utf-8")
        target = vault / TARGET_REL
        target.write_text("existing content", encoding="utf-8")

        run_cleanup(vault)

        assert todo.exists(), "TODO.md must remain (target exists)"
        assert target.read_text(encoding="utf-8") == "existing content"

    def test_no_todo_no_error(self, vault: Path) -> None:
        """No error when TODO.md is absent."""
        result = run_cleanup(vault)
        assert result.returncode == 0
        assert not (vault / TARGET_REL).exists()

    def test_migration_idempotent(self, vault: Path) -> None:
        """Second run after migration: exit 0, target still intact, TODO still gone."""
        (vault / "TODO.md").write_text("tasks", encoding="utf-8")

        run_cleanup(vault)
        result = run_cleanup(vault)

        assert result.returncode == 0
        assert (vault / TARGET_REL).read_text(encoding="utf-8") == "tasks"
        assert not (vault / "TODO.md").exists()

    def test_empty_todo_migrated(self, vault: Path) -> None:
        """Empty TODO.md migrated without error."""
        (vault / "TODO.md").write_text("", encoding="utf-8")
        target = vault / TARGET_REL

        run_cleanup(vault)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# 4. Idempotency & logging
# ---------------------------------------------------------------------------


class TestIdempotencyAndLogging:
    """Script must be safe to run multiple times and must write structured logs."""

    def test_double_run_no_error(self, vault: Path) -> None:
        """Two consecutive runs both exit 0."""
        clippings = vault / "Clippings"
        (clippings / "base.md").write_text("base", encoding="utf-8")
        (clippings / "base 1.md").write_text("dupe", encoding="utf-8")
        (vault / "TODO.md").write_text("todos", encoding="utf-8")

        r1 = run_cleanup(vault)
        r2 = run_cleanup(vault)

        assert r1.returncode == 0, f"First run failed: {r1.stderr}"
        assert r2.returncode == 0, f"Second run failed: {r2.stderr}"

    def test_log_file_created_with_markers(self, vault: Path) -> None:
        """Log file exists after run and contains START/DONE markers."""
        run_cleanup(vault)

        log = vault / ".automation" / "logs" / "automation.log"
        assert log.exists()
        content = log.read_text(encoding="utf-8")
        assert "--- START ---" in content
        assert "--- DONE ---" in content

    def test_log_appends_across_runs(self, vault: Path) -> None:
        """Consecutive runs append to log; markers appear once per run."""
        run_cleanup(vault)
        run_cleanup(vault)

        log = vault / ".automation" / "logs" / "automation.log"
        content = log.read_text(encoding="utf-8")
        assert content.count("--- START ---") == 2
        assert content.count("--- DONE ---") == 2

    def test_full_scenario_all_three_behaviors(self, vault: Path) -> None:
        """Integration: all three behaviors execute correctly in one pass."""
        clippings = vault / "Clippings"

        # 1. Duplicate pair
        (clippings / "guide.md").write_text("original", encoding="utf-8")
        (clippings / "guide 1.md").write_text("dupe", encoding="utf-8")

        # 2. Malformed name
        (clippings / "!bad-name.md").write_text("content", encoding="utf-8")

        # 3. TODO migration
        (vault / "TODO.md").write_text("tasks", encoding="utf-8")

        result = run_cleanup(vault)

        assert result.returncode == 0

        assert (clippings / "guide.md").exists()
        assert not (clippings / "guide 1.md").exists()

        assert (clippings / "bad-name.md").exists()
        assert not (clippings / "!bad-name.md").exists()

        assert not (vault / "TODO.md").exists()
        assert (vault / TARGET_REL).exists()

