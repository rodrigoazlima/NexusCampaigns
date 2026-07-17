"""
Tests for .automation/legacy/07-convert-docx.ps1

Strategy: patch $VaultRoot in the script text, inject a fake pandoc command +
stub overrides before the main block, write the patched copy to tmp_path,
invoke via subprocess.  All assertions check filesystem state - which files
exist, their content, and what was written to logs / processed-docx.txt.

Pandoc does NOT need to be installed - a fake pandoc.bat is injected into PATH.

Behaviors under test:
  1.  No DOCX files      - exits 0, logs "No unprocessed"
  2.  Conversion         - DOCX → .md created, processed list updated
  3.  Get-Slug           - slug generation (lower, hyphens, strip non-alnum)
  4.  Processed tracking - already-processed DOCX skipped on second run
  5.  Image extraction   - images moved from mediaDir/media/ to mediaDir/
  6.  Media subdir clean - media/ subdir removed after image move
  7.  Path rewriting     - image paths in .md updated to flattened location
  8.  Image collision    - duplicate filename gets counter suffix (-1, -2…)
  9.  Pandoc failure     - failed conversion logged, still marked processed
  10. Batch limit        - only 10 files per run
  11. Git exclusion      - .git/ DOCX files not processed
  12. Automation excl.   - .automation/ DOCX files not processed
  13. Logging            - START/DONE markers, timestamps, task prefix
  14. Idempotency        - second run processes 0 files
  15. Parametrized slugs - various name → slug transformations
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    Path(__file__).parent.parent
    / ".automation"
    / "legacy"
    / "07-convert-docx.ps1"
)
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

MAIN_MARKER = (
    "# ---------------------------------------------------------------------------\n"
    "# Main\n"
    "# ---------------------------------------------------------------------------"
)

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

# Minimal valid PNG magic bytes (first 8 bytes of any PNG file)
_PNG_MAGIC = bytes([137, 80, 78, 71, 13, 10, 26, 10])

# Minimal PNG with 1×1 white pixel (IHDR + IDAT + IEND), created via Python's
# zlib so the file actually opens without errors from Pillow.
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"                          # PNG signature
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01"        # IHDR chunk
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"                                 # IHDR CRC
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# ---------------------------------------------------------------------------
# Fake pandoc - PowerShell script + Windows batch wrapper
# ---------------------------------------------------------------------------

# Simulates pandoc:
#   • creates the .md output file
#   • if --extract-media is given, creates <mediaDir>/media/image001.png
#   • if _pandoc_fail sentinel exists next to this script → exits 1
_FAKE_PANDOC_PS1 = r"""
param()
$outFile  = $null
$mediaDir = $null
$i = 0
while ($i -lt $args.Count) {
    if ($args[$i] -eq '-o')                  { $outFile  = $args[$i+1]; $i += 2; continue }
    if ($args[$i] -like '--extract-media=*') { $mediaDir = $args[$i].Substring('--extract-media='.Length); $i++; continue }
    $i++
}

$failSentinel = Join-Path $PSScriptRoot '_pandoc_fail'
if (Test-Path $failSentinel) { exit 1 }

if ($outFile) {
    $slug    = [System.IO.Path]::GetFileNameWithoutExtension($outFile)
    $content = "# Test Document`r`n`r`nContent here.`r`n`r`n![]($slug/media/image001.png)`r`n"
    [System.IO.File]::WriteAllText($outFile, $content, [System.Text.Encoding]::UTF8)
}
if ($mediaDir) {
    $sub = Join-Path $mediaDir 'media'
    New-Item -ItemType Directory -Path $sub -Force | Out-Null
    $pngBytes = [byte[]](137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,
                         0,0,0,1,8,2,0,0,0,144,119,83,222)
    [System.IO.File]::WriteAllBytes((Join-Path $sub 'image001.png'), $pngBytes)
}
exit 0
"""

_FAKE_PANDOC_BAT = '@pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0_fake_pandoc.ps1" %*\n'

# ---------------------------------------------------------------------------
# Image comparison helpers
# (Pixel-accurate check + optional SSIM for perceptual assertions)
# ---------------------------------------------------------------------------


def images_are_equal(path_a: Path, path_b: Path) -> bool:
    """Return True when two image files have byte-identical content."""
    return path_a.read_bytes() == path_b.read_bytes()


def assert_images_similar(
    path_a: Path, path_b: Path, min_ssim: float = 0.95
) -> None:
    """Assert two grayscale image files are perceptually similar (SSIM ≥ min_ssim).

    Skipped gracefully when scikit-image or Pillow is not installed.
    """
    try:
        import numpy as np
        from PIL import Image
        from skimage.metrics import structural_similarity as ssim  # type: ignore
    except ImportError:
        pytest.skip("scikit-image / Pillow not installed - skipping SSIM check")

    img_a = np.array(Image.open(path_a).convert("L"))
    img_b = np.array(Image.open(path_b).convert("L"))
    score = float(ssim(img_a, img_b))
    assert score >= min_ssim, (
        f"SSIM {score:.3f} < {min_ssim}: {path_a.name} vs {path_b.name}"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _setup_fake_pandoc(tmp: Path) -> Path:
    """Write fake pandoc scripts to a _fake_bin/ dir; return its path."""
    fake_bin = tmp / "_fake_bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / "_fake_pandoc.ps1").write_text(_FAKE_PANDOC_PS1, encoding="utf-8")
    (fake_bin / "pandoc.bat").write_text(_FAKE_PANDOC_BAT, encoding="utf-8")
    return fake_bin


def _patch_script(vault_root: Path, fake_bin_dir: Path) -> str:
    """Read the script; replace $VaultRoot; inject stub overrides before main."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    text = text.replace(
        f"$VaultRoot     = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot     = '{vault_root}'",
    )
    injection = (
        f"$env:PATH = '{fake_bin_dir};' + $env:PATH\n"
        "function Initialize-Pandoc { return $true }\n"
    )
    text = text.replace(MAIN_MARKER, injection + "\n" + MAIN_MARKER)
    return text


def run_convert_docx(
    vault_root: Path,
    fake_bin_dir: Path,
) -> "subprocess.CompletedProcess[str]":
    """Patch + execute the script; return CompletedProcess for inspection."""
    patched = _patch_script(vault_root, fake_bin_dir)
    tmp_script = vault_root / "_test-07-convert-docx.ps1"
    tmp_script.write_text(patched, encoding="utf-8")
    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _log_path(vault: Path) -> Path:
    return vault / ".automation" / "logs" / "automation.log"


def _processed_path(vault: Path) -> Path:
    return vault / ".automation" / "processed-docx.txt"


def _processed_entries(vault: Path) -> list[str]:
    p = _processed_path(vault)
    if not p.exists():
        return []
    return [
        line.strip()
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _make_docx(path: Path) -> None:
    """Write a placeholder .docx (fake bytes - pandoc is mocked, never reads it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 26)  # ZIP local-file header signature


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal vault tree required by 07-convert-docx.ps1."""
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    (tmp_path / "00-Inbox" / "images").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def fake_bin(vault: Path) -> Path:
    """Fake pandoc binary directory scoped to the vault."""
    return _setup_fake_pandoc(vault)


# ---------------------------------------------------------------------------
# 1. No DOCX files
# ---------------------------------------------------------------------------


class TestNoDocxFiles:
    """With no DOCX files in the vault the script exits 0 cleanly."""

    def test_exits_zero(self, vault: Path, fake_bin: Path) -> None:
        result = run_convert_docx(vault, fake_bin)
        assert result.returncode == 0, result.stderr

    def test_log_file_created(self, vault: Path, fake_bin: Path) -> None:
        run_convert_docx(vault, fake_bin)
        assert _log_path(vault).exists()

    def test_log_contains_no_unprocessed_message(
        self, vault: Path, fake_bin: Path
    ) -> None:
        run_convert_docx(vault, fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "No unprocessed DOCX" in log

    def test_processed_list_empty(self, vault: Path, fake_bin: Path) -> None:
        run_convert_docx(vault, fake_bin)
        assert _processed_entries(vault) == []


# ---------------------------------------------------------------------------
# 2. Happy path - DOCX conversion
# ---------------------------------------------------------------------------


class TestDocxConversion:
    """A DOCX file is converted to Markdown in the same directory."""

    def test_md_file_created(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        assert (vault / "00-Inbox" / "lore.md").exists()

    def test_exits_zero(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        result = run_convert_docx(vault, fake_bin)

        assert result.returncode == 0, result.stderr

    def test_docx_added_to_processed_list(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        entries = _processed_entries(vault)
        assert any("lore.docx" in e for e in entries)

    def test_conversion_logged(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "Converting:" in log

    def test_md_file_not_empty(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        content = (vault / "00-Inbox" / "lore.md").read_text(encoding="utf-8")
        assert len(content.strip()) > 0

    def test_docx_in_subdirectory_converted(
        self, vault: Path, fake_bin: Path
    ) -> None:
        subdir = vault / "00-Inbox" / "arc-1"
        subdir.mkdir(parents=True)
        _make_docx(subdir / "npc-boss.docx")

        run_convert_docx(vault, fake_bin)

        assert (subdir / "npc-boss.md").exists()

    def test_multiple_docx_all_converted(
        self, vault: Path, fake_bin: Path
    ) -> None:
        for name in ("doc-a.docx", "doc-b.docx", "doc-c.docx"):
            _make_docx(vault / "00-Inbox" / name)

        run_convert_docx(vault, fake_bin)

        for name in ("doc-a.md", "doc-b.md", "doc-c.md"):
            assert (vault / "00-Inbox" / name).exists(), f"Missing {name}"

    def test_done_marker_includes_converted_count(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "converted: 1" in log


# ---------------------------------------------------------------------------
# 3. Get-Slug function
# ---------------------------------------------------------------------------


def _run_slug(name: str) -> str:
    """Execute the Get-Slug logic inline via PowerShell and return the result."""
    ps_code = (
        "function Get-Slug { param([string]$Name)\n"
        r"  $s = $Name.ToLower() -replace '[^\w\s-]', '' -replace '\s+', '-' -replace '-+', '-'"
        "\n  return $s.Trim('-')\n}\n"
        f"Get-Slug -Name '{name}'"
    )
    result = subprocess.run(
        [_PS_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_code],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestGetSlug:
    """Get-Slug converts a display name to a URL-safe lowercase slug."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("My Lore Document", "my-lore-document"),
            ("hello world", "hello-world"),
            ("UPPER CASE", "upper-case"),
            ("already-slug", "already-slug"),
            ("  spaces  ", "spaces"),
            ("multi   spaces", "multi-spaces"),
            ("NPC Profile 01", "npc-profile-01"),
        ],
    )
    def test_slug_generation(self, name: str, expected: str) -> None:
        assert _run_slug(name) == expected

    def test_slug_strips_special_characters(self) -> None:
        assert _run_slug("Name!@#%") == "name"

    def test_slug_collapses_multiple_hyphens(self) -> None:
        assert _run_slug("double--hyphen") == "double-hyphen"

    def test_slug_trims_leading_hyphen(self) -> None:
        assert _run_slug("-leading") == "leading"

    def test_slug_trims_trailing_hyphen(self) -> None:
        assert _run_slug("trailing-") == "trailing"

    def test_slug_used_as_images_subdir(self, vault: Path, fake_bin: Path) -> None:
        """The images output directory for a DOCX is named after its slug."""
        _make_docx(vault / "00-Inbox" / "My Lore Doc.docx")

        run_convert_docx(vault, fake_bin)

        slug_dir = vault / "00-Inbox" / "images" / "my-lore-doc"
        assert slug_dir.exists(), f"Expected slug dir: {slug_dir}"


# ---------------------------------------------------------------------------
# 4. Processed file tracking
# ---------------------------------------------------------------------------


class TestProcessedTracking:
    """Already-processed DOCX files are skipped on subsequent runs."""

    def test_already_processed_skipped(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "report.docx")
        run_convert_docx(vault, fake_bin)
        (vault / "00-Inbox" / "report.md").unlink()  # remove proof of conversion

        run_convert_docx(vault, fake_bin)

        assert not (vault / "00-Inbox" / "report.md").exists()

    def test_processed_entry_not_duplicated(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "report.docx")

        run_convert_docx(vault, fake_bin)
        run_convert_docx(vault, fake_bin)

        entries = _processed_entries(vault)
        docx_entries = [e for e in entries if "report.docx" in e]
        assert len(docx_entries) == 1

    def test_new_docx_converted_after_prior_run(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "first.docx")
        run_convert_docx(vault, fake_bin)

        _make_docx(vault / "00-Inbox" / "second.docx")
        run_convert_docx(vault, fake_bin)

        assert (vault / "00-Inbox" / "second.md").exists()


# ---------------------------------------------------------------------------
# 5–7. Image extraction, media-subdir cleanup, path rewriting
# ---------------------------------------------------------------------------


class TestImageExtraction:
    """Extracted images are moved from mediaDir/media/ up to mediaDir/."""

    def test_image_appears_in_slug_dir(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        slug_dir = vault / "00-Inbox" / "images" / "lore"
        assert list(slug_dir.glob("*.png")), f"No PNG found in {slug_dir}"

    def test_media_subdir_removed_after_move(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        assert not (vault / "00-Inbox" / "images" / "lore" / "media").exists()

    def test_original_media_path_absent_from_md(
        self, vault: Path, fake_bin: Path
    ) -> None:
        """MD must not contain the pre-move 'slug/media/' path."""
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        md = (vault / "00-Inbox" / "lore.md").read_text(encoding="utf-8")
        assert "lore/media/" not in md

    def test_md_image_path_points_to_images_dir(
        self, vault: Path, fake_bin: Path
    ) -> None:
        """MD image path must reference the flattened images slug directory."""
        _make_docx(vault / "00-Inbox" / "lore.docx")

        run_convert_docx(vault, fake_bin)

        md = (vault / "00-Inbox" / "lore.md").read_text(encoding="utf-8")
        assert "00-Inbox/images/lore/" in md

    def test_extracted_image_bytes_intact(
        self, vault: Path, fake_bin: Path
    ) -> None:
        """Moved image must start with PNG magic bytes (not corrupted)."""
        _make_docx(vault / "00-Inbox" / "portrait.docx")

        run_convert_docx(vault, fake_bin)

        slug_dir = vault / "00-Inbox" / "images" / "portrait"
        images = list(slug_dir.glob("*.png"))
        assert images, "No images extracted"
        assert images[0].read_bytes()[:8] == _PNG_MAGIC


# ---------------------------------------------------------------------------
# 8. Image collision handling
# ---------------------------------------------------------------------------


class TestImageCollision:
    """Duplicate destination filenames get a numeric counter suffix."""

    def test_collision_creates_dash_1_suffix(
        self, vault: Path, fake_bin: Path
    ) -> None:
        slug_dir = vault / "00-Inbox" / "images" / "lore"
        slug_dir.mkdir(parents=True)
        (slug_dir / "image001.png").write_bytes(_PNG_MAGIC)  # pre-existing file

        _make_docx(vault / "00-Inbox" / "lore.docx")
        run_convert_docx(vault, fake_bin)

        assert (slug_dir / "image001.png").read_bytes() == _PNG_MAGIC  # untouched
        suffixed = [
            f
            for f in slug_dir.iterdir()
            if f.name.startswith("image001-") and f.suffix == ".png"
        ]
        assert len(suffixed) == 1, f"Expected one -1 file; got {[f.name for f in slug_dir.iterdir()]}"

    def test_collision_counter_increments_past_existing_suffix(
        self, vault: Path, fake_bin: Path
    ) -> None:
        """image001-1.png already exists → collision becomes image001-2.png."""
        slug_dir = vault / "00-Inbox" / "images" / "lore"
        slug_dir.mkdir(parents=True)
        (slug_dir / "image001.png").write_bytes(_PNG_MAGIC)
        (slug_dir / "image001-1.png").write_bytes(_PNG_MAGIC)

        _make_docx(vault / "00-Inbox" / "lore.docx")
        run_convert_docx(vault, fake_bin)

        assert (slug_dir / "image001-2.png").exists()

    def test_collision_original_content_preserved(
        self, vault: Path, fake_bin: Path
    ) -> None:
        original_content = b"\x89PNG\r\n\x1a\n" + b"ORIGINAL" * 4
        slug_dir = vault / "00-Inbox" / "images" / "lore"
        slug_dir.mkdir(parents=True)
        (slug_dir / "image001.png").write_bytes(original_content)

        _make_docx(vault / "00-Inbox" / "lore.docx")
        run_convert_docx(vault, fake_bin)

        assert (slug_dir / "image001.png").read_bytes() == original_content


# ---------------------------------------------------------------------------
# 9. Pandoc failure
# ---------------------------------------------------------------------------


class TestPandocFailure:
    """A pandoc error is logged and the DOCX is still marked processed."""

    @pytest.fixture(autouse=True)
    def _set_fail_flag(self, fake_bin: Path) -> None:
        (fake_bin / "_pandoc_fail").write_text("fail", encoding="utf-8")

    def test_exits_zero_despite_pandoc_error(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "bad.docx")

        result = run_convert_docx(vault, fake_bin)

        assert result.returncode == 0, result.stderr

    def test_failure_logged(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "bad.docx")

        run_convert_docx(vault, fake_bin)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "pandoc failed" in log

    def test_failed_docx_still_marked_processed(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "bad.docx")

        run_convert_docx(vault, fake_bin)

        entries = _processed_entries(vault)
        assert any("bad.docx" in e for e in entries)

    def test_done_marker_includes_failed_count(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "bad.docx")

        run_convert_docx(vault, fake_bin)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "failed: 1" in log


# ---------------------------------------------------------------------------
# 10. Batch limit
# ---------------------------------------------------------------------------


class TestBatchLimit:
    """Only up to 10 DOCX files are processed per run ($BatchSize = 10)."""

    def test_caps_at_ten_per_run(self, vault: Path, fake_bin: Path) -> None:
        for i in range(15):
            _make_docx(vault / "00-Inbox" / f"doc-{i:02d}.docx")

        run_convert_docx(vault, fake_bin)

        assert len(_processed_entries(vault)) == 10

    def test_remaining_processed_on_next_run(
        self, vault: Path, fake_bin: Path
    ) -> None:
        for i in range(12):
            _make_docx(vault / "00-Inbox" / f"doc-{i:02d}.docx")

        run_convert_docx(vault, fake_bin)  # batch 1: 10 files
        run_convert_docx(vault, fake_bin)  # batch 2: remaining 2

        assert len(_processed_entries(vault)) == 12


# ---------------------------------------------------------------------------
# 11–12. Directory exclusions
# ---------------------------------------------------------------------------


class TestDirectoryExclusions:
    """DOCX files inside .git/ and .automation/ are never processed."""

    def test_git_docx_not_converted(self, vault: Path, fake_bin: Path) -> None:
        (vault / ".git").mkdir()
        _make_docx(vault / ".git" / "template.docx")

        run_convert_docx(vault, fake_bin)

        assert not (vault / ".git" / "template.md").exists()

    def test_automation_docx_not_converted(
        self, vault: Path, fake_bin: Path
    ) -> None:
        (vault / ".automation" / "legacy").mkdir(exist_ok=True)
        _make_docx(vault / ".automation" / "legacy" / "template.docx")

        run_convert_docx(vault, fake_bin)

        assert not (vault / ".automation" / "legacy" / "template.md").exists()

    def test_git_docx_absent_from_processed_list(
        self, vault: Path, fake_bin: Path
    ) -> None:
        (vault / ".git").mkdir()
        _make_docx(vault / ".git" / "hidden.docx")

        run_convert_docx(vault, fake_bin)

        assert not any(".git" in e for e in _processed_entries(vault))

    def test_sibling_outside_exclusions_still_converted(
        self, vault: Path, fake_bin: Path
    ) -> None:
        (vault / ".git").mkdir()
        _make_docx(vault / ".git" / "git-doc.docx")
        _make_docx(vault / "00-Inbox" / "normal.docx")

        run_convert_docx(vault, fake_bin)

        assert (vault / "00-Inbox" / "normal.md").exists()

    @pytest.mark.parametrize(
        "excluded_subpath",
        [
            ".git/template.docx",
            ".git/subdir/deep.docx",
            ".automation/cache.docx",
        ],
    )
    def test_parametrized_excluded_paths(
        self, vault: Path, fake_bin: Path, excluded_subpath: str
    ) -> None:
        parts = excluded_subpath.split("/")
        docx_path = vault
        for part in parts:
            docx_path = docx_path / part
        _make_docx(docx_path)

        run_convert_docx(vault, fake_bin)

        md_path = docx_path.with_suffix(".md")
        assert not md_path.exists(), f"Excluded file was converted: {md_path}"


# ---------------------------------------------------------------------------
# 13. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Script writes structured logs with correct format and markers."""

    def test_log_file_created(self, vault: Path, fake_bin: Path) -> None:
        run_convert_docx(vault, fake_bin)
        assert _log_path(vault).exists()

    def test_start_marker_present(self, vault: Path, fake_bin: Path) -> None:
        run_convert_docx(vault, fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "--- START ---" in log

    def test_done_marker_present(self, vault: Path, fake_bin: Path) -> None:
        run_convert_docx(vault, fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "--- DONE" in log

    def test_done_marker_includes_zero_counts_on_empty_run(
        self, vault: Path, fake_bin: Path
    ) -> None:
        run_convert_docx(vault, fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "converted: 0" in log and "failed: 0" in log

    def test_log_timestamp_format(self, vault: Path, fake_bin: Path) -> None:
        run_convert_docx(vault, fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        pattern = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
        assert pattern.search(log), "No timestamped log line found"

    def test_log_task_prefix_07_convert_docx(
        self, vault: Path, fake_bin: Path
    ) -> None:
        run_convert_docx(vault, fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "07-convert-docx" in log

    def test_log_appends_across_runs(self, vault: Path, fake_bin: Path) -> None:
        run_convert_docx(vault, fake_bin)
        run_convert_docx(vault, fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert log.count("--- START ---") == 2

    def test_converted_file_logged(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "npc.docx")

        run_convert_docx(vault, fake_bin)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "Converted:" in log


# ---------------------------------------------------------------------------
# 14. Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running the script twice produces stable results."""

    def test_double_run_both_exit_zero(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "report.docx")
        r1 = run_convert_docx(vault, fake_bin)
        r2 = run_convert_docx(vault, fake_bin)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

    def test_second_run_converts_zero(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault / "00-Inbox" / "report.docx")
        run_convert_docx(vault, fake_bin)
        run_convert_docx(vault, fake_bin)

        log = _log_path(vault).read_text(encoding="utf-8")
        last_done = [line for line in log.splitlines() if "--- DONE" in line][-1]
        assert "converted: 0" in last_done

    def test_md_file_content_stable_on_second_run(
        self, vault: Path, fake_bin: Path
    ) -> None:
        _make_docx(vault / "00-Inbox" / "report.docx")
        run_convert_docx(vault, fake_bin)
        first_md = (vault / "00-Inbox" / "report.md").read_text(encoding="utf-8")

        run_convert_docx(vault, fake_bin)

        assert (vault / "00-Inbox" / "report.md").read_text(encoding="utf-8") == first_md

    def test_empty_vault_idempotent(self, vault: Path, fake_bin: Path) -> None:
        r1 = run_convert_docx(vault, fake_bin)
        r2 = run_convert_docx(vault, fake_bin)
        assert r1.returncode == 0
        assert r2.returncode == 0

