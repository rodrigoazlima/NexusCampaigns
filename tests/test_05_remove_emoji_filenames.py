"""
Tests for .automation/legacy/05-remove-emoji-filenames.ps1

Strategy: patch $VaultRoot in the script text, write the patched copy to
tmp_path, invoke via subprocess.  All assertions check filesystem state -
which files exist and what names they have after the script runs.

No LLM or external services needed.

Behaviors under test:
   1.  Emoji prefix      - leading emoji stripped; file renamed
   2.  Emoji suffix      - trailing emoji stripped
   3.  Emoji in middle   - inline emoji stripped; double-space collapsed
   4.  Multiple emoji    - every emoji in one name stripped in one pass
   5.  Clean name        - file without emoji not renamed (idempotent)
   6.  Empty stem        - emoji-only filenames (e.g. "🎃.md") are skipped
   7.  Collision         - if clean name already exists, timestamp suffix added
   8.  Git excluded      - files inside .git/ are never renamed
   9.  Nested subdirs    - files in subdirectories are also renamed
  10.  Non-md extensions - .png/.jpg/.txt files with emoji names renamed too
  11.  Empty vault       - no files → exits 0 with "no emoji" log message
  12.  Logging           - automation.log created with START/DONE markers
  13.  Idempotency       - second run on already-clean vault renames nothing
  14.  Content preserved - byte content of renamed files is unchanged
  15.  Parametrized      - multiple emoji/name combos covered via parametrize
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    Path(__file__).parent.parent
    / ".automation"
    / "legacy"
    / "05-remove-emoji-filenames.ps1"
)
ORIGINAL_VAULT_ROOT = r"D:\Library\Obsidian\Personal\Notes"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_script(vault_root: Path) -> str:
    """Read script source; replace hardcoded $VaultRoot with the temp directory."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    text = text.replace(
        f"$VaultRoot = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot = '{vault_root}'",
    )
    return text


def run_remove_emoji(vault_root: Path) -> subprocess.CompletedProcess[str]:
    """Patch and execute the script; return CompletedProcess for inspection."""
    patched = _patch_script(vault_root)
    tmp_script = vault_root / "_test-05-remove-emoji-filenames.ps1"
    tmp_script.write_text(patched, encoding="utf-8")
    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _log_path(vault: Path) -> Path:
    return vault / ".automation" / "logs" / "automation.log"


def _filenames(directory: Path) -> set[str]:
    """Names of all files directly in *directory*, excluding the injected test script."""
    return {
        f.name
        for f in directory.iterdir()
        if f.is_file() and not f.name.startswith("_test-")
    }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Temp directory with the log folder the script expects to exist."""
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# 1–4. Core emoji stripping - happy path
# ---------------------------------------------------------------------------


class TestEmojiStripping:
    """Emoji characters are stripped from filenames and files are renamed."""

    def test_leading_emoji_removed(self, vault: Path) -> None:
        (vault / "🔥 dragon.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        names = _filenames(vault)
        assert "dragon.md" in names
        assert "🔥 dragon.md" not in names

    def test_trailing_emoji_removed(self, vault: Path) -> None:
        (vault / "warrior 🔥.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        names = _filenames(vault)
        assert "warrior.md" in names
        assert "warrior 🔥.md" not in names

    def test_middle_emoji_removed_and_spaces_collapsed(self, vault: Path) -> None:
        """Emoji surrounded by spaces → strip leaves double-space → collapsed."""
        (vault / "quest 🎃 boss.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        names = _filenames(vault)
        assert "quest boss.md" in names
        assert "quest 🎃 boss.md" not in names

    def test_multiple_emoji_all_stripped(self, vault: Path) -> None:
        (vault / "🔥 beast 🎃 lord.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        names = _filenames(vault)
        assert "beast lord.md" in names
        assert "🔥 beast 🎃 lord.md" not in names

    def test_adjacent_emoji_no_surrounding_spaces(self, vault: Path) -> None:
        """Emoji without surrounding spaces → adjacent non-emoji chars remain."""
        (vault / "npc-🎃-boss.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        names = _filenames(vault)
        assert "npc--boss.md" in names
        assert "npc-🎃-boss.md" not in names

    def test_script_exits_zero_on_rename(self, vault: Path) -> None:
        (vault / "🔥 beast.md").write_text("body", encoding="utf-8")

        result = run_remove_emoji(vault)

        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize(
        "original,expected",
        [
            ("🔥 fire beast.md", "fire beast.md"),
            ("📚 spell book.md", "spell book.md"),
            ("🎃🔥 double emoji.md", "double emoji.md"),
            ("npc-🎃-boss.md", "npc--boss.md"),
        ],
    )
    def test_parametrized_emoji_variants(
        self, vault: Path, original: str, expected: str
    ) -> None:
        """Various emoji placements all produce the expected clean name."""
        (vault / original).write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        names = _filenames(vault)
        assert original not in names
        # Accept the exact expected name or a space-collapsed/trimmed variant.
        assert expected in names or expected.replace("  ", " ").strip() in names


# ---------------------------------------------------------------------------
# 5. Clean names - not renamed
# ---------------------------------------------------------------------------


class TestCleanNames:
    """Files with no emoji in their names must not be renamed."""

    def test_clean_markdown_file_unchanged(self, vault: Path) -> None:
        (vault / "npc-warrior.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "npc-warrior.md").exists()

    def test_no_extra_files_created_for_clean_vault(self, vault: Path) -> None:
        expected = {"npc-warrior.md", "location-dungeon.md", "quest-main.md"}
        for name in expected:
            (vault / name).write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        assert _filenames(vault) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "plain.md",
            "npc-warrior-v2.md",
            "location 01 dungeon.md",
            "quest_main_arc.md",
            "report.txt",
            "portrait.png",
        ],
    )
    def test_various_clean_names_unchanged(self, vault: Path, name: str) -> None:
        (vault / name).write_bytes(b"data")

        run_remove_emoji(vault)

        assert (vault / name).exists()


# ---------------------------------------------------------------------------
# 6. Empty stem guard
# ---------------------------------------------------------------------------


class TestEmptyStemGuard:
    """Filenames that reduce to an empty stem after emoji strip are skipped."""

    def test_emoji_only_stem_skipped(self, vault: Path) -> None:
        """'🎃.md' → stem becomes empty → file NOT renamed."""
        (vault / "🎃.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "🎃.md").exists()

    def test_multiple_emoji_only_stem_skipped(self, vault: Path) -> None:
        (vault / "🔥🎃📚.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "🔥🎃📚.md").exists()

    def test_emoji_and_spaces_only_stem_skipped(self, vault: Path) -> None:
        """'🔥 🎃.md' → strip + trim → empty stem → skipped."""
        (vault / "🔥 🎃.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "🔥 🎃.md").exists()

    def test_skip_logged_for_empty_stem(self, vault: Path) -> None:
        (vault / "🎃.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "Skipped" in log


# ---------------------------------------------------------------------------
# 7. Collision handling
# ---------------------------------------------------------------------------


class TestCollisionHandling:
    """If the clean name already exists, the script appends a timestamp suffix."""

    def test_collision_emoji_file_renamed_with_suffix(self, vault: Path) -> None:
        (vault / "beast.md").write_text("canonical", encoding="utf-8")
        (vault / "🔥 beast.md").write_text("emoji version", encoding="utf-8")

        run_remove_emoji(vault)

        # Canonical file must be untouched.
        assert (vault / "beast.md").read_text(encoding="utf-8") == "canonical"
        # Emoji file renamed to "beast <timestamp>.md".
        suffixed = [
            f
            for f in vault.iterdir()
            if f.is_file() and f.name.startswith("beast ") and f.suffix == ".md"
        ]
        assert len(suffixed) == 1

    def test_collision_renamed_file_content_preserved(self, vault: Path) -> None:
        (vault / "boss.md").write_text("canonical", encoding="utf-8")
        (vault / "🎃 boss.md").write_text("emoji content", encoding="utf-8")

        run_remove_emoji(vault)

        suffixed = [
            f
            for f in vault.iterdir()
            if f.is_file() and f.name.startswith("boss ") and f.suffix == ".md"
        ]
        assert suffixed, "Collision-suffixed file not found"
        assert suffixed[0].read_text(encoding="utf-8") == "emoji content"

    def test_collision_suffix_matches_timestamp_pattern(self, vault: Path) -> None:
        """Timestamp suffix format must be yyyyMMdd-HHmmss."""
        (vault / "titan.md").write_text("canonical", encoding="utf-8")
        (vault / "🔥 titan.md").write_text("emoji", encoding="utf-8")

        run_remove_emoji(vault)

        suffixed = [
            f
            for f in vault.iterdir()
            if f.is_file() and f.name.startswith("titan ") and f.suffix == ".md"
        ]
        assert suffixed
        ts_pattern = re.compile(r"^titan \d{8}-\d{6}\.md$")
        assert ts_pattern.match(suffixed[0].name), (
            f"Unexpected collision name: {suffixed[0].name}"
        )


# ---------------------------------------------------------------------------
# 8. .git directory exclusion
# ---------------------------------------------------------------------------


class TestGitExclusion:
    """Files inside .git/ directories must never be renamed."""

    def test_git_dir_files_not_renamed(self, vault: Path) -> None:
        git_dir = vault / ".git"
        git_dir.mkdir()
        emoji_file = git_dir / "🔥 config.txt"
        emoji_file.write_text("git internal", encoding="utf-8")

        run_remove_emoji(vault)

        assert emoji_file.exists()
        assert not (git_dir / "config.txt").exists()

    def test_git_nested_subdir_files_not_renamed(self, vault: Path) -> None:
        nested = vault / ".git" / "refs" / "heads"
        nested.mkdir(parents=True)
        emoji_file = nested / "🎃 main.txt"
        emoji_file.write_text("ref", encoding="utf-8")

        run_remove_emoji(vault)

        assert emoji_file.exists()
        assert not (nested / "main.txt").exists()

    def test_non_git_sibling_still_renamed(self, vault: Path) -> None:
        """Regular files outside .git/ are still renamed even when .git/ exists."""
        (vault / ".git").mkdir()
        (vault / ".git" / "🎃 internal.txt").write_text("git", encoding="utf-8")
        (vault / "🔥 normal.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "normal.md").exists()


# ---------------------------------------------------------------------------
# 9. Nested subdirectories
# ---------------------------------------------------------------------------


class TestNestedDirectories:
    """Script uses -Recurse, so files in subdirectories are also renamed."""

    def test_single_subdir_file_renamed(self, vault: Path) -> None:
        subdir = vault / "00-Inbox" / "images"
        subdir.mkdir(parents=True)
        (subdir / "🔥 portrait.png").write_bytes(b"\x89PNG\r\n")

        run_remove_emoji(vault)

        assert (subdir / "portrait.png").exists()
        assert not (subdir / "🔥 portrait.png").exists()

    def test_deeply_nested_file_renamed(self, vault: Path) -> None:
        deep = vault / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "📚 notes.txt").write_text("deep note", encoding="utf-8")

        run_remove_emoji(vault)

        assert (deep / "notes.txt").exists()
        assert not (deep / "📚 notes.txt").exists()

    def test_files_across_multiple_subdirs_renamed(self, vault: Path) -> None:
        dirs_and_names = [
            (vault / "00-Inbox", "🔥 a.md"),
            (vault / "01-Processing", "🎃 b.md"),
        ]
        for subdir, name in dirs_and_names:
            subdir.mkdir(exist_ok=True)
            (subdir / name).write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "00-Inbox" / "a.md").exists()
        assert (vault / "01-Processing" / "b.md").exists()


# ---------------------------------------------------------------------------
# 10. Non-markdown file types
# ---------------------------------------------------------------------------


class TestNonMarkdownFiles:
    """The script renames every file type, not only .md."""

    @pytest.mark.parametrize("ext", [".png", ".jpg", ".txt", ".pdf", ".mp3"])
    def test_various_extensions_renamed(self, vault: Path, ext: str) -> None:
        name = f"🔥 asset{ext}"
        (vault / name).write_bytes(b"data")

        run_remove_emoji(vault)

        names = _filenames(vault)
        assert f"asset{ext}" in names
        assert name not in names


# ---------------------------------------------------------------------------
# 11. Empty vault
# ---------------------------------------------------------------------------


class TestEmptyVault:
    """An empty vault must exit 0 and log a 'no emoji' message."""

    def test_empty_vault_exits_zero(self, vault: Path) -> None:
        result = run_remove_emoji(vault)
        assert result.returncode == 0, result.stderr

    def test_empty_vault_log_created(self, vault: Path) -> None:
        run_remove_emoji(vault)
        assert _log_path(vault).exists()

    def test_empty_vault_logs_no_emoji_found(self, vault: Path) -> None:
        run_remove_emoji(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "No emoji filenames found" in log


# ---------------------------------------------------------------------------
# 12. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Script must write structured logs with correct format and markers."""

    def test_log_file_created(self, vault: Path) -> None:
        run_remove_emoji(vault)
        assert _log_path(vault).exists()

    def test_start_marker_present(self, vault: Path) -> None:
        run_remove_emoji(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "--- START ---" in log

    def test_done_marker_present(self, vault: Path) -> None:
        run_remove_emoji(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "--- DONE" in log

    def test_done_marker_includes_rename_count(self, vault: Path) -> None:
        (vault / "🔥 beast.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "--- DONE (1 renamed) ---" in log

    def test_rename_action_logged(self, vault: Path) -> None:
        (vault / "🔥 dragon.md").write_text("body", encoding="utf-8")

        run_remove_emoji(vault)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "Renamed:" in log

    def test_log_line_timestamp_format(self, vault: Path) -> None:
        """Every log line must start with [YYYY-MM-DD HH:mm:ss]."""
        run_remove_emoji(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        pattern = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
        assert pattern.search(log), "No timestamped log line found"

    def test_log_appends_across_runs(self, vault: Path) -> None:
        run_remove_emoji(vault)
        run_remove_emoji(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert log.count("--- START ---") == 2

    def test_log_task_prefix_in_lines(self, vault: Path) -> None:
        run_remove_emoji(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "05-remove-emoji-filenames" in log


# ---------------------------------------------------------------------------
# 13. Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running the script twice produces identical filesystem state."""

    def test_double_run_both_exit_zero(self, vault: Path) -> None:
        (vault / "🔥 beast.md").write_text("body", encoding="utf-8")
        r1 = run_remove_emoji(vault)
        r2 = run_remove_emoji(vault)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

    def test_filenames_stable_after_second_run(self, vault: Path) -> None:
        (vault / "🔥 beast.md").write_text("body", encoding="utf-8")
        run_remove_emoji(vault)
        names_after_first = _filenames(vault)

        run_remove_emoji(vault)

        assert _filenames(vault) == names_after_first

    def test_second_run_logs_zero_renames(self, vault: Path) -> None:
        (vault / "🔥 beast.md").write_text("body", encoding="utf-8")
        run_remove_emoji(vault)
        run_remove_emoji(vault)

        log = _log_path(vault).read_text(encoding="utf-8")
        last_done = [line for line in log.splitlines() if "--- DONE" in line][-1]
        assert "(0 renamed)" in last_done

    def test_empty_vault_idempotent(self, vault: Path) -> None:
        r1 = run_remove_emoji(vault)
        r2 = run_remove_emoji(vault)
        assert r1.returncode == 0
        assert r2.returncode == 0


# ---------------------------------------------------------------------------
# 14. File content preserved
# ---------------------------------------------------------------------------


class TestContentPreserved:
    """Renaming must not alter the byte content of any file."""

    def test_text_content_unchanged_after_rename(self, vault: Path) -> None:
        content = "# NPC Profile\n\nDragon warrior.\n"
        (vault / "🔥 npc-dragon.md").write_text(content, encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "npc-dragon.md").read_text(encoding="utf-8") == content

    def test_binary_content_unchanged_after_rename(self, vault: Path) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        (vault / "🔥 portrait.png").write_bytes(png_bytes)

        run_remove_emoji(vault)

        assert (vault / "portrait.png").read_bytes() == png_bytes

    def test_unicode_content_unchanged_after_rename(self, vault: Path) -> None:
        content = "# Ñoño Mágico\n\náéíóú ãõ ç - em dash\n"
        (vault / "🔥 unicode-note.md").write_text(content, encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "unicode-note.md").read_text(encoding="utf-8") == content

    def test_multiple_files_content_all_preserved(self, vault: Path) -> None:
        files = {
            "🔥 a.md": "content A",
            "🎃 b.md": "content B",
            "📚 c.md": "content C",
        }
        for name, body in files.items():
            (vault / name).write_text(body, encoding="utf-8")

        run_remove_emoji(vault)

        assert (vault / "a.md").read_text(encoding="utf-8") == "content A"
        assert (vault / "b.md").read_text(encoding="utf-8") == "content B"
        assert (vault / "c.md").read_text(encoding="utf-8") == "content C"

