"""
Tests for .automation/06-classify-images.ps1

Strategy: patch $VaultRoot in script text, inject PowerShell stubs overriding
Test-LMStudioOnline / Invoke-VisionLLM / Test-IsToken / Invoke-TokenFaceMatch
before the main block, write patched copy to tmp_path, invoke via subprocess.
All assertions check filesystem state - which files exist, JSON index content,
markdown frontmatter, and log output.

No real LM Studio server, System.Drawing, or Python face-matcher needed.

Behaviors under test:
  1.  LM Studio offline      - early exit 0, no files renamed, index unchanged
  2.  No unprocessed images  - exit 0, "No unprocessed images" logged
  3.  Portrait happy path    - rename, draft md, JSON index
  4.  Battlemap happy path   - battlemap-{env}.ext naming + location entity type
  5.  Scene happy path       - scene-{env}.ext naming + location entity type
  6.  Body happy path        - {race}-{class}-{element}.body.ext naming
  7.  Token naming           - .token.ext suffix, token:true in frontmatter
  8.  Filename collision     - existing file bumped to -1 counter suffix
  9.  JSON index v2 schema   - sha256 key, pathIndex, required fields
 10.  Already indexed        - pathIndex entry → skipped on second run
 11.  Draft markdown         - AGENTS.md-compliant YAML frontmatter + embed
 12.  LLM failed             - pseudoKey "path:..." in index, failed count logged
 13.  LLM connection-error   - image NOT indexed, classified count unaffected
 14.  Logging                - START/DONE markers, timestamp format, task prefix
 15.  Idempotency            - second run adds no new index entries, exits 0
 16.  Queue vision update    - inbox-queue.json vision=done for processed image
 17.  Multiple image formats - .png/.jpg/.jpeg files discovered and renamed
 18.  Parametrized types     - all four types produce correct filename suffix
 19.  Invalid LLM values     - unknown type/race/element sanitized to defaults
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "06-classify-images.ps1"
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

# Unique string present exactly once, just before the main execution block.
MAIN_ANCHOR = "Write-Log '--- START ---'"

# ---------------------------------------------------------------------------
# Pillow image helpers
# ---------------------------------------------------------------------------


def make_png(path: Path, width: int = 32, height: int = 32) -> Path:
    """Create a minimal solid-colour RGB PNG. Returns *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=(100, 150, 200)).save(str(path), "PNG")
    return path


def make_token_png(path: Path, width: int = 64, height: int = 64) -> Path:
    """RGBA PNG with transparent corners - passes Test-IsToken in the real script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (width, height), color=(100, 150, 200, 255))
    px = img.load()
    for x, y in [
        (0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1),
        (width // 2, 0), (0, height // 2), (width - 1, height // 2), (width // 2, height - 1),
    ]:
        px[x, y] = (0, 0, 0, 0)
    img.save(str(path), "PNG")
    return path


def make_jpg(path: Path, width: int = 32, height: int = 32) -> Path:
    """Create a minimal JPEG at *path*. Returns *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=(200, 100, 50)).save(str(path), "JPEG")
    return path


# ---------------------------------------------------------------------------
# Stub / patch helpers
# ---------------------------------------------------------------------------


def _ps_bool(value: bool) -> str:
    return "$true" if value else "$false"


def _stub_classify_result(
    status: str = "ok",
    img_type: str = "portrait",
    race: str = "human",
    cls: str = "warrior",
    element: str = "none",
    environment: str = "none",
    description: str = "Test image description.",
) -> str:
    """Return a PowerShell hashtable literal for Invoke-VisionLLM to return."""
    return (
        f"@{{ Status = '{status}'; Type = '{img_type}'; Race = '{race}'; "
        f"Class = '{cls}'; Element = '{element}'; Environment = '{environment}'; "
        f"Description = '{description}' }}"
    )


def _stub_block(
    lm_online: bool = True,
    classify_result: str | None = None,
    is_token: bool = False,
    face_match_result: str = "$null",
) -> str:
    """PowerShell stubs injected before the main block."""
    if classify_result is None:
        classify_result = _stub_classify_result()
    return (
        f"function Test-LMStudioOnline {{ return {_ps_bool(lm_online)} }}\n"
        f"function Invoke-VisionLLM {{\n"
        f"    param([string]$ImagePath)\n"
        f"    return {classify_result}\n"
        f"}}\n"
        f"function Test-IsToken {{\n"
        f"    param([string]$ImagePath)\n"
        f"    return {_ps_bool(is_token)}\n"
        f"}}\n"
        f"function Invoke-TokenFaceMatch {{\n"
        f"    param([string]$TokenPath, [string[]]$Candidates)\n"
        f"    return {face_match_result}\n"
        f"}}\n"
    )


def _patch_script(
    vault_root: Path,
    lm_online: bool = True,
    classify_result: str | None = None,
    is_token: bool = False,
    face_match_result: str = "$null",
) -> str:
    """Read script, replace $VaultRoot, inject stubs before the main block."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    text = text.replace(
        f"$VaultRoot      = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot      = '{vault_root}'",
    )
    stubs = _stub_block(
        lm_online=lm_online,
        classify_result=classify_result,
        is_token=is_token,
        face_match_result=face_match_result,
    )
    text = text.replace(MAIN_ANCHOR, stubs + "\n" + MAIN_ANCHOR)
    return text


def run_classify(
    vault_root: Path,
    *,
    lm_online: bool = True,
    classify_result: str | None = None,
    is_token: bool = False,
    face_match_result: str = "$null",
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    """Patch and execute the classification script; return CompletedProcess."""
    patched = _patch_script(
        vault_root,
        lm_online=lm_online,
        classify_result=classify_result,
        is_token=is_token,
        face_match_result=face_match_result,
    )
    tmp_script = vault_root / "_test-06-classify-images.ps1"
    tmp_script.write_text(patched, encoding="utf-8")
    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _log_path(vault: Path) -> Path:
    return vault / ".automation" / "logs" / "automation.log"


def _json_index_path(vault: Path) -> Path:
    return vault / ".automation" / "processed-images.json"


def _images_dir(vault: Path) -> Path:
    return vault / "00-Inbox" / "images"


def _processing_dir(vault: Path) -> Path:
    return vault / "01-Processing"


def _load_json_index(vault: Path) -> dict:
    p = _json_index_path(vault)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _ok_entries(vault: Path) -> list[dict]:
    """Return all JSON index entries with status='ok'."""
    idx = _load_json_index(vault)
    return [
        v for v in idx.get("images", {}).values()
        if isinstance(v, dict) and v.get("status") == "ok"
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Generator[Path, None, None]:
    """Minimal vault layout expected by 06-classify-images.ps1."""
    (tmp_path / "00-Inbox" / "images" / "A1").mkdir(parents=True)
    (tmp_path / "01-Processing").mkdir(parents=True)
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    yield tmp_path


# ---------------------------------------------------------------------------
# 1. LM Studio offline
# ---------------------------------------------------------------------------


class TestLMStudioOffline:
    """Script exits 0 without renaming anything when LM Studio is unreachable."""

    def test_exits_zero_when_offline(self, vault: Path) -> None:
        result = run_classify(vault, lm_online=False)
        assert result.returncode == 0, result.stderr

    def test_source_file_not_renamed_when_offline(self, vault: Path) -> None:
        src = _images_dir(vault) / "A1" / "portrait001.png"
        make_png(src)

        run_classify(vault, lm_online=False)

        assert src.exists(), "Source file must survive an offline run unchanged"

    def test_json_index_not_populated_when_offline(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault, lm_online=False)

        assert _ok_entries(vault) == []

    def test_log_offline_message(self, vault: Path) -> None:
        run_classify(vault, lm_online=False)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "offline" in log.lower()


# ---------------------------------------------------------------------------
# 2. No unprocessed images
# ---------------------------------------------------------------------------


class TestNoUnprocessedImages:
    """Empty inbox → exit 0, log message."""

    def test_exits_zero_with_empty_inbox(self, vault: Path) -> None:
        result = run_classify(vault)
        assert result.returncode == 0, result.stderr

    def test_log_no_unprocessed_message(self, vault: Path) -> None:
        run_classify(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert "No unprocessed images found" in log


# ---------------------------------------------------------------------------
# 3. Portrait happy path
# ---------------------------------------------------------------------------


class TestPortraitHappyPath:
    """Portrait classification → rename, draft md, JSON index, wiki row."""

    def test_file_renamed_to_portrait_slug(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        assert (_images_dir(vault) / "A1" / "human-warrior-none.portrait.png").exists()
        assert not (_images_dir(vault) / "A1" / "portrait001.png").exists()

    def test_draft_md_written_to_processing(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        assert (_processing_dir(vault) / "human-warrior-none.portrait.md").exists()

    def test_exit_code_zero(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        result = run_classify(vault)
        assert result.returncode == 0, result.stderr

    def test_json_index_has_one_ok_entry(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        assert len(_ok_entries(vault)) == 1

    def test_json_entry_fields_correct(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        entry = _ok_entries(vault)[0]
        assert entry["type"] == "portrait"
        assert entry["race"] == "human"
        assert entry["class"] == "warrior"
        assert entry["element"] == "none"
        assert entry["isToken"] is False
        assert "sha256" in entry
        assert "path" in entry
        assert "processedAt" in entry

    def test_path_index_populated(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        idx = _load_json_index(vault)
        assert len(idx.get("pathIndex", {})) >= 1


# ---------------------------------------------------------------------------
# 4. Battlemap happy path
# ---------------------------------------------------------------------------

_BATTLEMAP_RESULT = _stub_classify_result(
    img_type="battlemap", race="none", cls="none", element="none", environment="dungeon"
)


class TestBattlemapHappyPath:
    """Battlemap → battlemap-{env}.ext + location entity type."""

    def test_renamed_to_battlemap_slug(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "map001.png")

        run_classify(vault, classify_result=_BATTLEMAP_RESULT)

        assert (_images_dir(vault) / "A1" / "battlemap-dungeon.png").exists()

    def test_draft_entity_type_is_location(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "map001.png")

        run_classify(vault, classify_result=_BATTLEMAP_RESULT)

        md = (_processing_dir(vault) / "battlemap-dungeon.md").read_text(encoding="utf-8")
        assert "type: location" in md

    def test_draft_has_environment_field(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "map001.png")

        run_classify(vault, classify_result=_BATTLEMAP_RESULT)

        md = (_processing_dir(vault) / "battlemap-dungeon.md").read_text(encoding="utf-8")
        assert "environment: dungeon" in md

    @pytest.mark.parametrize("environment", [
        "dungeon", "cave", "forest", "city", "tavern",
        "desert", "snow", "sea", "swamp", "ruins", "temple",
        "castle", "plains", "mountain",
    ])
    def test_various_environments_produce_correct_slug(
        self, vault: Path, environment: str
    ) -> None:
        make_png(_images_dir(vault) / "A1" / f"map-{environment}.png")
        result = _stub_classify_result(
            img_type="battlemap", race="none", cls="none",
            element="none", environment=environment,
        )

        run_classify(vault, classify_result=result)

        assert (_images_dir(vault) / "A1" / f"battlemap-{environment}.png").exists()


# ---------------------------------------------------------------------------
# 5. Scene happy path
# ---------------------------------------------------------------------------

_SCENE_RESULT = _stub_classify_result(
    img_type="scene", race="none", cls="none", element="none", environment="forest"
)


class TestSceneHappyPath:
    """Scene → scene-{env}.ext + location entity type."""

    def test_renamed_to_scene_slug(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "scenery001.png")

        run_classify(vault, classify_result=_SCENE_RESULT)

        assert (_images_dir(vault) / "A1" / "scene-forest.png").exists()

    def test_draft_entity_type_is_location(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "scenery001.png")

        run_classify(vault, classify_result=_SCENE_RESULT)

        md = (_processing_dir(vault) / "scene-forest.md").read_text(encoding="utf-8")
        assert "type: location" in md


# ---------------------------------------------------------------------------
# 6. Body happy path
# ---------------------------------------------------------------------------

_BODY_RESULT = _stub_classify_result(
    img_type="body", race="orc", cls="warrior", element="fire"
)


class TestBodyHappyPath:
    """Body → {race}-{class}-{element}.body.ext + creature entity type."""

    def test_renamed_to_body_slug(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "creature001.png")

        run_classify(vault, classify_result=_BODY_RESULT)

        assert (_images_dir(vault) / "A1" / "orc-warrior-fire.body.png").exists()

    def test_draft_entity_type_is_creature(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "creature001.png")

        run_classify(vault, classify_result=_BODY_RESULT)

        md = (_processing_dir(vault) / "orc-warrior-fire.body.md").read_text(encoding="utf-8")
        assert "type: creature" in md


# ---------------------------------------------------------------------------
# 7. Token naming
# ---------------------------------------------------------------------------


class TestTokenNaming:
    """Token images get .token.ext suffix and token:true in frontmatter."""

    def test_token_renamed_with_token_suffix(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "char_frame.png")

        run_classify(vault, is_token=True)

        assert (_images_dir(vault) / "A1" / "human-warrior-none.token.png").exists()

    def test_token_draft_has_token_true(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "char_frame.png")

        run_classify(vault, is_token=True)

        md = (_processing_dir(vault) / "human-warrior-none.token.md").read_text(encoding="utf-8")
        assert "token: true" in md

    def test_token_draft_has_token_tag(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "char_frame.png")

        run_classify(vault, is_token=True)

        md = (_processing_dir(vault) / "human-warrior-none.token.md").read_text(encoding="utf-8")
        assert "  - token" in md

    def test_token_json_entry_is_token_true(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "char_frame.png")

        run_classify(vault, is_token=True)

        entry = _ok_entries(vault)[0]
        assert entry.get("isToken") is True


# ---------------------------------------------------------------------------
# 8. Filename collision handling
# ---------------------------------------------------------------------------


class TestCollisionHandling:
    """When clean name already exists the old file is bumped to a -1 counter."""

    def test_existing_file_bumped_to_counter(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "human-warrior-none.portrait.png")
        make_png(_images_dir(vault) / "A1" / "portrait002.png")

        run_classify(vault)

        assert (_images_dir(vault) / "A1" / "human-warrior-none-1.portrait.png").exists()
        assert (_images_dir(vault) / "A1" / "human-warrior-none.portrait.png").exists()

    def test_companion_md_bumped_alongside_image(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "human-warrior-none.portrait.png")
        (_processing_dir(vault) / "human-warrior-none.portrait.md").write_text(
            "# original draft\n", encoding="utf-8"
        )
        make_png(_images_dir(vault) / "A1" / "portrait002.png")

        run_classify(vault)

        assert (_processing_dir(vault) / "human-warrior-none-1.portrait.md").exists()

    def test_bumped_file_content_preserved(self, vault: Path) -> None:
        existing = _images_dir(vault) / "A1" / "human-warrior-none.portrait.png"
        make_png(existing)
        original_bytes = existing.read_bytes()
        make_png(_images_dir(vault) / "A1" / "portrait002.png")

        run_classify(vault)

        bumped = _images_dir(vault) / "A1" / "human-warrior-none-1.portrait.png"
        assert bumped.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# 9. JSON index v2 schema
# ---------------------------------------------------------------------------


class TestJsonIndexSchema:
    """Index must conform to v2 schema: sha256 keys, pathIndex, required fields."""

    def test_version_is_2(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        assert _load_json_index(vault).get("version") == 2

    def test_image_key_is_lowercase_hex_sha256(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        ok_keys = [
            k for k, v in _load_json_index(vault).get("images", {}).items()
            if isinstance(v, dict) and v.get("status") == "ok"
        ]
        assert len(ok_keys) == 1
        assert re.fullmatch(r"[0-9a-f]{64}", ok_keys[0]), (
            f"Key is not a valid lowercase sha256: {ok_keys[0]}"
        )

    def test_path_index_maps_to_sha256(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        idx = _load_json_index(vault)
        ok_sha256s = {
            k for k, v in idx.get("images", {}).items()
            if isinstance(v, dict) and v.get("status") == "ok"
        }
        path_index_values = set(idx.get("pathIndex", {}).values())
        assert ok_sha256s <= path_index_values

    def test_entry_path_uses_backslash(self, vault: Path) -> None:
        """Stored path must use Windows backslash separators."""
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        entry = _ok_entries(vault)[0]
        assert "\\" in entry.get("path", ""), (
            f"Expected backslash path, got: {entry.get('path')}"
        )


# ---------------------------------------------------------------------------
# 10. Already indexed (idempotency via pathIndex)
# ---------------------------------------------------------------------------


class TestAlreadyIndexed:
    """Images already in pathIndex are skipped on re-runs."""

    def test_renamed_file_unchanged_on_second_run(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        run_classify(vault)
        renamed = _images_dir(vault) / "A1" / "human-warrior-none.portrait.png"
        assert renamed.exists()
        before_bytes = renamed.read_bytes()

        run_classify(vault)

        assert renamed.read_bytes() == before_bytes

    def test_second_run_adds_no_new_index_entries(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        run_classify(vault)
        count_after_first = len(_load_json_index(vault).get("images", {}))

        run_classify(vault)

        count_after_second = len(_load_json_index(vault).get("images", {}))
        assert count_after_second == count_after_first

    def test_second_run_exits_zero(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        run_classify(vault)
        result = run_classify(vault)
        assert result.returncode == 0, result.stderr

    def test_second_run_logs_zero_classified(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        run_classify(vault)
        _log_path(vault).write_text("", encoding="utf-8")

        run_classify(vault)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "classified: 0" in log


# ---------------------------------------------------------------------------
# 11. Draft markdown content
# ---------------------------------------------------------------------------


class TestDraftMarkdown:
    """Companion markdown must be AGENTS.md-compliant YAML frontmatter."""

    def _draft(self, vault: Path) -> str:
        return (_processing_dir(vault) / "human-warrior-none.portrait.md").read_text(
            encoding="utf-8"
        )

    def _run_portrait(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        run_classify(vault)

    def test_starts_with_yaml_fence(self, vault: Path) -> None:
        self._run_portrait(vault)
        assert self._draft(vault).startswith("---\n")

    def test_has_required_frontmatter_fields(self, vault: Path) -> None:
        self._run_portrait(vault)
        md = self._draft(vault)
        for field in ("id:", "type:", "status:", "quality:", "created:", "sha256:", "reviewed:"):
            assert field in md, f"Missing field: {field}"

    def test_status_is_draft(self, vault: Path) -> None:
        self._run_portrait(vault)
        assert "status: draft" in self._draft(vault)

    def test_quality_is_zero(self, vault: Path) -> None:
        self._run_portrait(vault)
        assert "quality: 0" in self._draft(vault)

    def test_reviewed_is_false(self, vault: Path) -> None:
        self._run_portrait(vault)
        assert "reviewed: false" in self._draft(vault)

    def test_npc_entity_type_for_portrait(self, vault: Path) -> None:
        self._run_portrait(vault)
        assert "type: npc" in self._draft(vault)

    def test_has_image_embed(self, vault: Path) -> None:
        self._run_portrait(vault)
        md = self._draft(vault)
        assert "![[" in md and "human-warrior-none.portrait.png" in md

    def test_has_sha256_in_body(self, vault: Path) -> None:
        self._run_portrait(vault)
        md = self._draft(vault)
        assert re.search(r"sha256: `[0-9a-f]{64}`", md), (
            "sha256 line not found in draft body"
        )

    def test_description_in_body(self, vault: Path) -> None:
        result = _stub_classify_result(description="A fierce warrior stands tall.")
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        run_classify(vault, classify_result=result)
        assert "A fierce warrior stands tall." in self._draft(vault)

    def test_race_class_element_in_frontmatter_for_portrait(self, vault: Path) -> None:
        self._run_portrait(vault)
        md = self._draft(vault)
        assert "race: human" in md
        assert "class: warrior" in md
        assert "element: none" in md


# ---------------------------------------------------------------------------
# 12. LLM failed → pseudoKey in index
# ---------------------------------------------------------------------------

_FAILED_RESULT = _stub_classify_result(status="failed")


class TestLLMFailed:
    """When LLM fails, image gets a 'path:...' pseudoKey with status=failed."""

    def test_failed_entry_added_to_index(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault, classify_result=_FAILED_RESULT)

        failed = [
            v for v in _load_json_index(vault).get("images", {}).values()
            if isinstance(v, dict) and v.get("status") == "failed"
        ]
        assert len(failed) == 1

    def test_failed_pseudokey_has_path_prefix(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault, classify_result=_FAILED_RESULT)

        pseudo_keys = [
            k for k in _load_json_index(vault).get("images", {})
            if k.startswith("path:")
        ]
        assert len(pseudo_keys) == 1

    def test_failed_entry_preserves_original_name(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault, classify_result=_FAILED_RESULT)

        entry = next(
            v for v in _load_json_index(vault).get("images", {}).values()
            if isinstance(v, dict) and v.get("status") == "failed"
        )
        assert entry.get("originalName") == "portrait001.png"

    def test_failed_count_in_done_marker(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault, classify_result=_FAILED_RESULT)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "failed: 1" in log


# ---------------------------------------------------------------------------
# 15. LLM connection-error → image NOT indexed
# ---------------------------------------------------------------------------

_CONNECTION_ERROR_RESULT = _stub_classify_result(status="connection-error")


class TestConnectionError:
    """Connection-error means server went down mid-batch; image must not be indexed."""

    def test_connection_error_image_not_indexed(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault, classify_result=_CONNECTION_ERROR_RESULT)

        assert _load_json_index(vault).get("images", {}) == {}

    def test_connection_error_exits_zero(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        result = run_classify(vault, classify_result=_CONNECTION_ERROR_RESULT)
        assert result.returncode == 0, result.stderr

    def test_connection_error_log_message(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault, classify_result=_CONNECTION_ERROR_RESULT)

        log = _log_path(vault).read_text(encoding="utf-8")
        assert "connection" in log.lower() or "Skipping" in log


# ---------------------------------------------------------------------------
# 16. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Structured logs with START/DONE markers, timestamps, and task prefix."""

    def test_log_file_created(self, vault: Path) -> None:
        run_classify(vault)
        assert _log_path(vault).exists()

    def test_start_marker_present(self, vault: Path) -> None:
        run_classify(vault)
        assert "--- START ---" in _log_path(vault).read_text(encoding="utf-8")

    def test_done_marker_present(self, vault: Path) -> None:
        run_classify(vault)
        assert "--- DONE" in _log_path(vault).read_text(encoding="utf-8")

    def test_done_marker_has_classified_count(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")

        run_classify(vault)

        assert "classified: 1" in _log_path(vault).read_text(encoding="utf-8")

    def test_done_marker_has_elapsed(self, vault: Path) -> None:
        run_classify(vault)
        assert "elapsed:" in _log_path(vault).read_text(encoding="utf-8")

    def test_log_timestamp_format(self, vault: Path) -> None:
        run_classify(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", log), (
            "No timestamped log line found"
        )

    def test_log_task_prefix(self, vault: Path) -> None:
        run_classify(vault)
        assert "06-classify-images" in _log_path(vault).read_text(encoding="utf-8")

    def test_log_appends_across_runs(self, vault: Path) -> None:
        run_classify(vault)
        run_classify(vault)
        log = _log_path(vault).read_text(encoding="utf-8")
        assert log.count("--- START ---") == 2


# ---------------------------------------------------------------------------
# 17. Idempotency (full second-run check)
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Two runs on the same vault produce identical filesystem state."""

    def test_double_run_both_exit_zero(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        r1 = run_classify(vault)
        r2 = run_classify(vault)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

    def test_no_duplicate_file_on_second_run(self, vault: Path) -> None:
        make_png(_images_dir(vault) / "A1" / "portrait001.png")
        run_classify(vault)
        run_classify(vault)
        # Counter-bumped variant must not appear
        assert not (_images_dir(vault) / "A1" / "human-warrior-none-1.portrait.png").exists()

    def test_empty_vault_idempotent(self, vault: Path) -> None:
        r1 = run_classify(vault)
        r2 = run_classify(vault)
        assert r1.returncode == 0
        assert r2.returncode == 0


# ---------------------------------------------------------------------------
# 18. Queue vision update
# ---------------------------------------------------------------------------


class TestQueueVisionUpdate:
    """inbox-queue.json: vision agent marked done for processed image."""

    def test_vision_marked_done(self, vault: Path) -> None:
        img = _images_dir(vault) / "A1" / "portrait001.png"
        make_png(img)
        # Relative path as the script computes it (backslash, no leading separator)
        rel = str(img.relative_to(vault))

        queue_path = vault / ".automation" / "inbox-queue.json"
        queue = {rel: {"agents": {"vision": "pending", "tags": "pending"}}}
        queue_path.write_text(json.dumps(queue), encoding="utf-8")

        run_classify(vault)

        q = json.loads(queue_path.read_text(encoding="utf-8"))
        any_done = any(
            isinstance(v, dict) and v.get("agents", {}).get("vision") == "done"
            for v in q.values()
        )
        assert any_done, "No queue entry has vision=done after classification"


# ---------------------------------------------------------------------------
# 19. Multiple image formats
# ---------------------------------------------------------------------------


class TestMultipleImageFormats:
    """Script discovers and renames .png, .jpg, .jpeg files."""

    @pytest.mark.parametrize("ext,make_fn", [
        (".png", make_png),
        (".jpg", make_jpg),
        (".jpeg", make_jpg),
    ])
    def test_format_discovered_and_renamed(
        self, vault: Path, ext: str, make_fn
    ) -> None:
        src = _images_dir(vault) / "A1" / f"source{ext}"
        make_fn(src)

        run_classify(vault)

        renamed = _images_dir(vault) / "A1" / f"human-warrior-none.portrait{ext}"
        assert renamed.exists(), f"Expected {renamed.name} to exist after classification"

    def test_multiple_images_all_processed_in_one_batch(self, vault: Path) -> None:
        for i in range(3):
            make_png(_images_dir(vault) / "A1" / f"portrait{i:03d}.png")

        run_classify(vault)

        assert len(_ok_entries(vault)) == 3


# ---------------------------------------------------------------------------
# 20. Parametrized classification types
# ---------------------------------------------------------------------------


class TestClassificationTypes:
    """All four image types produce the correct filename suffix."""

    @pytest.mark.parametrize("img_type,race,cls,elem,env,expected_name", [
        ("portrait",  "human",  "warrior", "none",  "none",    "human-warrior-none.portrait.png"),
        ("body",      "orc",    "mage",    "fire",  "none",    "orc-mage-fire.body.png"),
        ("battlemap", "none",   "none",    "none",  "dungeon", "battlemap-dungeon.png"),
        ("scene",     "none",   "none",    "none",  "forest",  "scene-forest.png"),
    ])
    def test_type_produces_correct_filename(
        self, vault: Path, img_type: str, race: str, cls: str,
        elem: str, env: str, expected_name: str,
    ) -> None:
        make_png(_images_dir(vault) / "A1" / "input.png")
        result = _stub_classify_result(
            img_type=img_type, race=race, cls=cls, element=elem, environment=env,
        )

        run_classify(vault, classify_result=result)

        assert (_images_dir(vault) / "A1" / expected_name).exists()


# ---------------------------------------------------------------------------
# 21. Invalid LLM values - sanitization
# ---------------------------------------------------------------------------


class TestInvalidLLMValues:
    """Unknown values from LLM are replaced with safe defaults."""

    def test_invalid_type_defaults_to_portrait(self, vault: Path) -> None:
        """LLM returning an unknown type falls back to 'portrait'."""
        make_png(_images_dir(vault) / "A1" / "input.png")

        run_classify(vault, classify_result=_stub_classify_result(img_type="unknown-xyz"))

        entry = _ok_entries(vault)[0]
        assert entry.get("type") == "portrait"

    def test_invalid_race_stored_as_unknown(self, vault: Path) -> None:
        """Unknown race is stored as 'unknown' rather than the raw LLM value."""
        make_png(_images_dir(vault) / "A1" / "input.png")

        run_classify(vault, classify_result=_stub_classify_result(race="elf-dragon-hybrid"))

        entry = _ok_entries(vault)[0]
        assert entry.get("race") == "unknown"

    def test_invalid_element_defaults_to_none(self, vault: Path) -> None:
        """Unknown element is stored as 'none'."""
        make_png(_images_dir(vault) / "A1" / "input.png")

        run_classify(vault, classify_result=_stub_classify_result(element="plasma"))

        entry = _ok_entries(vault)[0]
        assert entry.get("element") == "none"

    def test_invalid_class_defaults_to_none(self, vault: Path) -> None:
        """Unknown class is stored as 'none'."""
        make_png(_images_dir(vault) / "A1" / "input.png")

        run_classify(vault, classify_result=_stub_classify_result(cls="supervillain"))

        entry = _ok_entries(vault)[0]
        assert entry.get("class") == "none"

