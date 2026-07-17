"""
Tests for .automation/11-ingestion-agent.ps1 - Ingestion Agent

Strategy: patch $VaultRoot in the script text, inject no-op function stubs
for irrelevant phases, write the patched script to tmp_path, and invoke
via subprocess.  All assertions check filesystem state and JSON outputs.
No LLM, no pandoc install needed (fake pandoc.bat injected into PATH).

Behaviors under test:
  1.  get_slug               - lowercase, hyphens, strip specials, trim edges
  2.  remove_emoji_filenames - emoji stripped; clean files untouched; empty stem
                               skipped; .git/ excluded; collision preserved; idempotent
  3.  register_inbox_files   - queue.json created; correct type per extension;
                               correct agent slots per type; required fields present;
                               idempotent on re-run; new files added on next run
  4.  convert_docx_files     - fake pandoc: .md created, processed tracked;
                               pandoc failure: logged, still marked; idempotent
  5.  integration            - full script exits 0; START/DONE log markers;
                               per-task log file; elapsed time; queue depth
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "11-ingestion-agent.ps1"
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

# Unique anchor: first executable line in the main block (no Unicode dashes needed)
_MAIN_ANCHOR = 'New-Item -ItemType Directory -Force -Path "$AutoDir\\logs" | Out-Null'

# ---------------------------------------------------------------------------
# Fake pandoc - avoids installing pandoc on CI
# ---------------------------------------------------------------------------

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
    $content = "# Test Document`r`n`r`nContent here.`r`n"
    [System.IO.File]::WriteAllText($outFile, $content, [System.Text.Encoding]::UTF8)
}
if ($mediaDir) {
    New-Item -ItemType Directory -Path (Join-Path $mediaDir 'media') -Force | Out-Null
}
exit 0
"""

_FAKE_PANDOC_BAT = '@pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0_fake_pandoc.ps1" %*\n'


def _setup_fake_pandoc(tmp: Path) -> Path:
    fake_bin = tmp / "_fake_bin"
    fake_bin.mkdir(exist_ok=True)
    (fake_bin / "_fake_pandoc.ps1").write_text(_FAKE_PANDOC_PS1, encoding="utf-8")
    (fake_bin / "pandoc.bat").write_text(_FAKE_PANDOC_BAT, encoding="utf-8")
    return fake_bin


# ---------------------------------------------------------------------------
# Image comparison helpers
# ---------------------------------------------------------------------------


def images_are_equal(a: Path, b: Path) -> bool:
    """True when two image files have byte-identical content."""
    return a.read_bytes() == b.read_bytes()


def assert_images_similar(a: Path, b: Path, min_ssim: float = 0.90) -> None:
    """Assert SSIM >= min_ssim between two image files; skipped if skimage absent."""
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
# Script patching and execution
# ---------------------------------------------------------------------------

# Phase-level no-op stubs
_STUB_NO_EMOJI = "function Remove-EmojiFilenames { Write-Log 'Emoji: stubbed (test)' }"
_STUB_NO_DOCX  = "function Convert-DocxFiles     { Write-Log 'DOCX: stubbed (test)' }"
_STUB_NO_QUEUE = "function Register-InboxFiles   { Write-Log 'Queue: stubbed (test)' }"


def _patch_script(
    vault_root: Path,
    stubs: str = "",
    fake_bin: Optional[Path] = None,
) -> str:
    """Read script; replace $VaultRoot; inject stubs before the main block."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    text = text.replace(
        f"$VaultRoot     = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot     = '{vault_root}'",
    )
    parts: list[str] = []
    if fake_bin:
        parts.append(f"$env:PATH = '{fake_bin};' + $env:PATH")
        parts.append("function Initialize-Pandoc { return $true }")
    if stubs:
        parts.append(stubs)
    if parts:
        injection = "\n".join(parts) + "\n"
        text = text.replace(_MAIN_ANCHOR, injection + _MAIN_ANCHOR)
    return text


def _run_script(
    vault_root: Path,
    stubs: str = "",
    fake_bin: Optional[Path] = None,
    timeout: int = 60,
) -> "subprocess.CompletedProcess[str]":
    """Patch and execute the script; return CompletedProcess for inspection."""
    patched = _patch_script(vault_root, stubs=stubs, fake_bin=fake_bin)
    tmp_script = vault_root / "_test-11-ingestion-agent.ps1"
    tmp_script.write_text(patched, encoding="utf-8")
    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Path and JSON helpers
# ---------------------------------------------------------------------------


def _queue_path(vault: Path) -> Path:
    return vault / ".automation" / "inbox-queue.json"


def _queue_data(vault: Path) -> dict:
    p = _queue_path(vault)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _log_path(vault: Path) -> Path:
    return vault / ".automation" / "logs" / "automation.log"


def _make_inbox_file(vault: Path, rel: str, content: bytes = b"test") -> Path:
    """Create a file inside vault/00-Inbox/ at the given relative sub-path."""
    p = vault / "00-Inbox" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _make_docx(vault: Path, rel: str) -> Path:
    """Write a placeholder .docx (ZIP magic bytes; pandoc is mocked)."""
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 26)
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal vault tree required by 11-ingestion-agent.ps1."""
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    (tmp_path / "00-Inbox" / "images").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def fake_bin(vault: Path) -> Path:
    """Fake pandoc binary directory scoped to the vault fixture."""
    return _setup_fake_pandoc(vault)


# ---------------------------------------------------------------------------
# 1. Get-Slug
# ---------------------------------------------------------------------------


def _run_get_slug(name: str) -> str:
    """Inline the Get-Slug function from the script and invoke it."""
    ps = (
        "function Get-Slug { param([string]$Name)\n"
        "    ($Name.ToLower() -replace '[^\\w\\s-]','' -replace '\\s+','-'"
        " -replace '-+','-').Trim('-')\n"
        "}\n"
        f"Get-Slug '{name}'"
    )
    r = subprocess.run(
        [_PS_EXE, "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return r.stdout.strip()


class TestGetSlug:
    """Get-Slug converts display names to URL-safe lowercase slugs."""

    @pytest.mark.parametrize("name,expected", [
        ("My Document Name",    "my-document-name"),
        ("Hello World",         "hello-world"),
        ("A1 Annun Ascendant",  "a1-annun-ascendant"),
        ("UPPERCASE",           "uppercase"),
        ("already-a-slug",      "already-a-slug"),
        ("  leading spaces  ",  "leading-spaces"),
        ("--dashes--",          "dashes"),
        ("foo---bar",           "foo-bar"),
        ("Hello! World?",       "hello-world"),
        ("npc_underscore",      "npc_underscore"),
    ])
    def test_known_transformations(self, name: str, expected: str) -> None:
        assert _run_get_slug(name) == expected

    def test_output_is_lowercase(self) -> None:
        result = _run_get_slug("LOUD NAMES")
        assert result == result.lower()

    def test_no_consecutive_dashes(self) -> None:
        assert "--" not in _run_get_slug("foo -- bar")

    def test_no_leading_or_trailing_dash(self) -> None:
        result = _run_get_slug("!!! hello !!!")
        assert not result.startswith("-") and not result.endswith("-")

    def test_spaces_become_single_dash(self) -> None:
        assert _run_get_slug("a b") == "a-b"

    def test_empty_string_returns_empty(self) -> None:
        assert _run_get_slug("  ") == ""


# ---------------------------------------------------------------------------
# 2. Remove-EmojiFilenames
# ---------------------------------------------------------------------------


class TestRemoveEmojiFilenames:
    """Remove-EmojiFilenames strips emoji chars from filenames in 00-Inbox/."""

    _STUBS = "\n".join([_STUB_NO_DOCX, _STUB_NO_QUEUE])

    def test_emoji_prefix_stripped(self, vault: Path) -> None:
        _make_inbox_file(vault, "🐉 dragon.png")
        _run_script(vault, stubs=self._STUBS)
        assert (vault / "00-Inbox" / "dragon.png").exists()

    def test_original_emoji_filename_gone(self, vault: Path) -> None:
        _make_inbox_file(vault, "🐉 dragon.png")
        _run_script(vault, stubs=self._STUBS)
        names = {f.name for f in (vault / "00-Inbox").iterdir()}
        assert "🐉 dragon.png" not in names

    def test_clean_file_not_renamed(self, vault: Path) -> None:
        _make_inbox_file(vault, "clean-file.png")
        _run_script(vault, stubs=self._STUBS)
        assert (vault / "00-Inbox" / "clean-file.png").exists()

    def test_emoji_only_filename_not_removed(self, vault: Path) -> None:
        """Empty-stem files are skipped - the original file must survive."""
        _make_inbox_file(vault, "🎃.md")
        _run_script(vault, stubs=self._STUBS)
        assert (vault / "00-Inbox" / "🎃.md").exists()

    def test_git_files_not_renamed(self, vault: Path) -> None:
        git_file = vault / "00-Inbox" / ".git" / "🎃 key.md"
        git_file.parent.mkdir(parents=True, exist_ok=True)
        git_file.write_text("secret", encoding="utf-8")
        _run_script(vault, stubs=self._STUBS)
        assert git_file.exists()

    def test_nested_subdir_file_renamed(self, vault: Path) -> None:
        _make_inbox_file(vault, "A1/🎭 hero.png")
        _run_script(vault, stubs=self._STUBS)
        assert (vault / "00-Inbox" / "A1" / "hero.png").exists()

    def test_collision_does_not_overwrite_original(self, vault: Path) -> None:
        """If clean name already exists, original content is preserved."""
        _make_inbox_file(vault, "hero.png", b"original")
        _make_inbox_file(vault, "🐉 hero.png", b"duplicate")
        _run_script(vault, stubs=self._STUBS)
        assert (vault / "00-Inbox" / "hero.png").read_bytes() == b"original"

    def test_byte_content_preserved_after_rename(self, vault: Path) -> None:
        content = b"important-data-payload"
        _make_inbox_file(vault, "🐉 data.bin", content)
        _run_script(vault, stubs=self._STUBS)
        assert (vault / "00-Inbox" / "data.bin").read_bytes() == content

    def test_idempotent_on_second_run(self, vault: Path) -> None:
        _make_inbox_file(vault, "already-clean.png")
        _run_script(vault, stubs=self._STUBS)
        result = _run_script(vault, stubs=self._STUBS)
        assert result.returncode == 0
        assert (vault / "00-Inbox" / "already-clean.png").exists()

    @pytest.mark.parametrize("filename", [
        "🔥 fire.png",
        "⚔️ sword.txt",
        "🧙 wizard.docx",
    ])
    def test_various_emoji_removed_from_filename(
        self, vault: Path, filename: str
    ) -> None:
        _make_inbox_file(vault, filename)
        _run_script(vault, stubs=self._STUBS)
        names = {f.name for f in (vault / "00-Inbox").iterdir()}
        assert filename not in names, f"Emoji filename still present: {filename!r}"

    def test_non_md_extensions_renamed(self, vault: Path) -> None:
        for fname in ["🎭 hero.png", "⚔️ sword.txt", "📜 lore.pdf"]:
            _make_inbox_file(vault, fname)
        _run_script(vault, stubs=self._STUBS)
        names = {f.name for f in (vault / "00-Inbox").iterdir()}
        assert not any("🎭" in n or "⚔️" in n or "📜" in n for n in names)


# ---------------------------------------------------------------------------
# 3. Register-InboxFiles
# ---------------------------------------------------------------------------

_IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]
_DOC_EXTS   = [".md", ".txt", ".pdf", ".docx"]
_OTHER_EXTS = [".xyz", ".mp3", ".zip"]

_QUEUE_ONLY_STUBS = "\n".join([_STUB_NO_EMOJI, _STUB_NO_DOCX])


class TestQueueCreated:
    """Register-InboxFiles creates inbox-queue.json after scanning 00-Inbox/."""

    def test_queue_file_created(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/A1/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert _queue_path(vault).exists()

    def test_queue_file_is_valid_json(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/A1/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        data = _queue_data(vault)
        assert isinstance(data, dict)

    def test_empty_inbox_produces_empty_queue(self, vault: Path) -> None:
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        if _queue_path(vault).exists():
            assert _queue_data(vault) == {}

    def test_queue_file_is_utf8(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/npc.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        _queue_path(vault).read_bytes().decode("utf-8")  # must not raise


class TestQueueFileTypes:
    """Each file extension is classified as image, document, or other."""

    @pytest.mark.parametrize("ext", _IMAGE_EXTS)
    def test_image_extension_classified_as_image(self, vault: Path, ext: str) -> None:
        _make_inbox_file(vault, f"images/hero{ext}")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        entry = next((v for k, v in _queue_data(vault).items() if k.endswith(ext)), None)
        assert entry is not None
        assert entry["type"] == "image", f"ext={ext!r}: expected 'image', got {entry['type']!r}"

    @pytest.mark.parametrize("ext", _DOC_EXTS)
    def test_doc_extension_classified_as_document(self, vault: Path, ext: str) -> None:
        _make_inbox_file(vault, f"docs/lore{ext}")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        entry = next((v for k, v in _queue_data(vault).items() if k.endswith(ext)), None)
        assert entry is not None
        assert entry["type"] == "document", f"ext={ext!r}: expected 'document', got {entry['type']!r}"

    @pytest.mark.parametrize("ext", _OTHER_EXTS)
    def test_unknown_extension_classified_as_other(self, vault: Path, ext: str) -> None:
        _make_inbox_file(vault, f"misc/file{ext}")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        entry = next((v for k, v in _queue_data(vault).items() if k.endswith(ext)), None)
        assert entry is not None
        assert entry["type"] == "other", f"ext={ext!r}: expected 'other', got {entry['type']!r}"


class TestQueueAgentSlots:
    """Agent slots are assigned correctly based on file type."""

    def _entry(self, vault: Path, ext: str) -> dict:
        return next((v for k, v in _queue_data(vault).items() if k.endswith(ext)), {})

    def test_image_vision_is_pending(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".png")["agents"]["vision"] == "pending"

    def test_image_lore_is_pending(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".png")["agents"]["lore"] == "pending"

    def test_image_classification_is_pending(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".png")["agents"]["classification"] == "pending"

    def test_document_wiki_is_pending(self, vault: Path) -> None:
        _make_inbox_file(vault, "docs/lore.md")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".md")["agents"]["wiki"] == "pending"

    def test_document_classification_is_pending(self, vault: Path) -> None:
        _make_inbox_file(vault, "docs/lore.md")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".md")["agents"]["classification"] == "pending"

    def test_document_has_no_vision_agent(self, vault: Path) -> None:
        _make_inbox_file(vault, "docs/lore.md")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert "vision" not in self._entry(vault, ".md").get("agents", {})

    def test_document_has_no_lore_agent(self, vault: Path) -> None:
        _make_inbox_file(vault, "docs/lore.md")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert "lore" not in self._entry(vault, ".md").get("agents", {})

    def test_other_classification_is_skip(self, vault: Path) -> None:
        _make_inbox_file(vault, "misc/file.xyz")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".xyz")["agents"]["classification"] == "skip"

    def test_other_vision_is_skip(self, vault: Path) -> None:
        _make_inbox_file(vault, "misc/file.xyz")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".xyz")["agents"]["vision"] == "skip"

    def test_other_lore_is_skip(self, vault: Path) -> None:
        _make_inbox_file(vault, "misc/file.xyz")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".xyz")["agents"]["lore"] == "skip"

    def test_other_wiki_is_skip(self, vault: Path) -> None:
        _make_inbox_file(vault, "misc/file.xyz")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert self._entry(vault, ".xyz")["agents"]["wiki"] == "skip"


class TestQueueStructure:
    """Every queue entry has required fields in the expected formats."""

    def _first_entry(self, vault: Path) -> tuple[str, dict]:
        data = _queue_data(vault)
        return next(iter(data.items()))

    def test_entry_has_ingested_at(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        _, entry = self._first_entry(vault)
        assert "ingestedAt" in entry

    def test_ingested_at_is_iso_format(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        _, entry = self._first_entry(vault)
        assert re.match(r"^\d{4}-\d{2}-\d{2}", entry["ingestedAt"])

    def test_entry_has_type_field(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        _, entry = self._first_entry(vault)
        assert "type" in entry

    def test_entry_has_agents_field(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        _, entry = self._first_entry(vault)
        assert "agents" in entry

    def test_agents_is_dict(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        _, entry = self._first_entry(vault)
        assert isinstance(entry["agents"], dict)

    def test_queue_key_is_relative_path(self, vault: Path) -> None:
        """Keys must be relative paths - not absolute (no drive letter)."""
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        key, _ = self._first_entry(vault)
        assert not key.startswith("D:\\") and not key.startswith("C:\\")

    def test_queue_key_contains_filename(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/unique-hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert any("unique-hero.png" in k for k in _queue_data(vault))

    @pytest.mark.parametrize("fname,expected_type", [
        ("hero.png",  "image"),
        ("lore.md",   "document"),
        ("audio.mp3", "other"),
    ])
    def test_type_values_are_valid(
        self, vault: Path, fname: str, expected_type: str
    ) -> None:
        _make_inbox_file(vault, fname)
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        entry = next(
            (v for k, v in _queue_data(vault).items() if k.endswith(fname)),
            None,
        )
        assert entry is not None
        assert entry["type"] == expected_type


class TestQueueIdempotency:
    """Register-InboxFiles does not duplicate entries across multiple runs."""

    def test_second_run_no_new_entries(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        keys_first = set(_queue_data(vault).keys())
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        keys_second = set(_queue_data(vault).keys())
        assert keys_first == keys_second

    def test_ingested_at_unchanged_on_rerun(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        ts_first = next(iter(_queue_data(vault).values()))["ingestedAt"]
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        ts_second = next(iter(_queue_data(vault).values()))["ingestedAt"]
        assert ts_first == ts_second

    def test_new_file_added_on_second_run(self, vault: Path) -> None:
        _make_inbox_file(vault, "images/hero.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        _make_inbox_file(vault, "images/villain.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert len(_queue_data(vault)) == 2

    def test_queue_count_matches_file_count(self, vault: Path) -> None:
        for i in range(4):
            _make_inbox_file(vault, f"images/npc{i}.png")
        _run_script(vault, stubs=_QUEUE_ONLY_STUBS)
        assert len(_queue_data(vault)) == 4


# ---------------------------------------------------------------------------
# 4. Convert-DocxFiles
# ---------------------------------------------------------------------------

_DOCX_ONLY_STUBS = "\n".join([_STUB_NO_EMOJI, _STUB_NO_QUEUE])


class TestDocxConversion:
    """Convert-DocxFiles converts .docx to GFM Markdown via pandoc."""

    def test_exits_zero_no_docx(self, vault: Path, fake_bin: Path) -> None:
        result = _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        assert result.returncode == 0, result.stderr

    def test_md_file_created_from_docx(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault, "00-Inbox/lore.docx")
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        assert (vault / "00-Inbox" / "lore.md").exists()

    def test_processed_list_updated(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault, "00-Inbox/lore.docx")
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        processed = (vault / ".automation" / "processed-docx.txt").read_text(encoding="utf-8")
        assert "lore.docx" in processed

    def test_media_dir_created_for_slug(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault, "00-Inbox/my-campaign-notes.docx")
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        assert (vault / "00-Inbox" / "images" / "my-campaign-notes").exists()

    def test_already_processed_docx_skipped(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault, "00-Inbox/lore.docx")
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        (vault / "00-Inbox" / "lore.md").unlink()
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        assert not (vault / "00-Inbox" / "lore.md").exists()

    def test_pandoc_failure_logged(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault, "00-Inbox/bad.docx")
        (fake_bin / "_pandoc_fail").touch()
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "pandoc failed" in log.lower() or "failed" in log.lower()

    def test_git_docx_excluded(self, vault: Path, fake_bin: Path) -> None:
        hidden = vault / ".git" / "00-Inbox" / "secret.docx"
        hidden.parent.mkdir(parents=True, exist_ok=True)
        hidden.write_bytes(b"PK\x03\x04" + b"\x00" * 26)
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        assert not (vault / ".git" / "00-Inbox" / "secret.md").exists()

    def test_automation_docx_excluded(self, vault: Path, fake_bin: Path) -> None:
        hidden = vault / ".automation" / "internal.docx"
        hidden.write_bytes(b"PK\x03\x04" + b"\x00" * 26)
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        assert not (vault / ".automation" / "internal.md").exists()

    @pytest.mark.parametrize("stem,expected_slug", [
        ("My Campaign Notes",  "my-campaign-notes"),
        ("world-building",     "world-building"),
        ("Arc01 The Beginning", "arc01-the-beginning"),
    ])
    def test_slug_derived_from_docx_stem(
        self, vault: Path, fake_bin: Path, stem: str, expected_slug: str
    ) -> None:
        _make_docx(vault, f"00-Inbox/{stem}.docx")
        _run_script(vault, stubs=_DOCX_ONLY_STUBS, fake_bin=fake_bin)
        assert (vault / "00-Inbox" / "images" / expected_slug).exists()


# ---------------------------------------------------------------------------
# 5. Integration - full script with all three phases
# ---------------------------------------------------------------------------


class TestIntegration:
    """Full script run: all three phases execute and produce expected outputs."""

    def test_exits_zero(self, vault: Path, fake_bin: Path) -> None:
        result = _run_script(vault, fake_bin=fake_bin)
        assert result.returncode == 0, result.stderr

    def test_log_has_start_marker(self, vault: Path, fake_bin: Path) -> None:
        _run_script(vault, fake_bin=fake_bin)
        assert "--- START ---" in _log_path(vault).read_text(encoding="utf-8")

    def test_log_has_done_marker(self, vault: Path, fake_bin: Path) -> None:
        _run_script(vault, fake_bin=fake_bin)
        assert "--- DONE" in _log_path(vault).read_text(encoding="utf-8")

    def test_log_has_task_prefix(self, vault: Path, fake_bin: Path) -> None:
        _run_script(vault, fake_bin=fake_bin)
        assert "[11-ingestion-agent]" in _log_path(vault).read_text(encoding="utf-8")

    def test_elapsed_time_in_log(self, vault: Path, fake_bin: Path) -> None:
        _run_script(vault, fake_bin=fake_bin)
        assert "elapsed:" in _log_path(vault).read_text(encoding="utf-8")

    def test_per_task_log_file_created(self, vault: Path, fake_bin: Path) -> None:
        _run_script(vault, fake_bin=fake_bin)
        task_logs = list((vault / ".automation" / "logs").glob("11-ingestion-agent_*.log"))
        assert len(task_logs) >= 1

    def test_queue_depth_logged(self, vault: Path, fake_bin: Path) -> None:
        _make_inbox_file(vault, "images/A1/hero.png")
        _run_script(vault, fake_bin=fake_bin)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "Queue depth" in log

    def test_queue_created_for_image(self, vault: Path, fake_bin: Path) -> None:
        _make_inbox_file(vault, "images/A1/hero.png")
        _run_script(vault, fake_bin=fake_bin)
        assert any("hero.png" in k for k in _queue_data(vault))

    def test_image_type_set_correctly_full_run(self, vault: Path, fake_bin: Path) -> None:
        _make_inbox_file(vault, "images/A1/hero.png")
        _run_script(vault, fake_bin=fake_bin)
        entry = next(
            (v for k, v in _queue_data(vault).items() if "hero.png" in k),
            None,
        )
        assert entry is not None
        assert entry["type"] == "image"

    def test_second_full_run_idempotent(self, vault: Path, fake_bin: Path) -> None:
        _make_inbox_file(vault, "images/A1/hero.png")
        _run_script(vault, fake_bin=fake_bin)
        keys_first = set(_queue_data(vault).keys())
        _run_script(vault, fake_bin=fake_bin)
        keys_second = set(_queue_data(vault).keys())
        assert keys_first == keys_second

    def test_docx_converted_and_queued(self, vault: Path, fake_bin: Path) -> None:
        _make_docx(vault, "00-Inbox/worldbuilding.docx")
        _run_script(vault, fake_bin=fake_bin)
        # DOCX converted to .md
        assert (vault / "00-Inbox" / "worldbuilding.md").exists()
        # .md registered in queue as 'document'
        entry = next(
            (v for k, v in _queue_data(vault).items() if "worldbuilding.md" in k),
            None,
        )
        assert entry is not None
        assert entry["type"] == "document"

    def test_emoji_renamed_and_queued(self, vault: Path, fake_bin: Path) -> None:
        """Emoji-renamed file appears in queue under its clean name."""
        _make_inbox_file(vault, "images/🐉 dragon.png")
        _run_script(vault, fake_bin=fake_bin)
        # After rename, 'dragon.png' should be in queue
        assert any("dragon.png" in k for k in _queue_data(vault))

