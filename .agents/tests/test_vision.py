"""Tests for vision.tools.classify_images."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

import vision.tools.classify_images as _mod
from shared.models import Element, Environment, ImageType, VisionClassification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clf(
    type_: str = "portrait",
    ancestry: str = "human",
    char_class: str = "fighter",
    creature_type: str = "none",
    element: str = "dark",
    environment: str = "none",
    description: str = "A grim warrior.",
) -> VisionClassification:
    return VisionClassification(
        type=ImageType(type_),
        ancestry=ancestry,
        **{"class": char_class},
        creature_type=creature_type,
        element=Element(element),
        environment=Environment(environment),
        description=description,
    )


# ---------------------------------------------------------------------------
# Vault layout fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    kb = tmp_path / "knowledge-base"
    (kb / "00-Inbox" / "images").mkdir(parents=True)
    (kb / "01-Processing").mkdir(parents=True)
    (kb / "02-Library").mkdir(parents=True)
    return kb


@pytest.fixture
def patch_roots(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(_mod, "_VAULT_ROOT",   vault)
    monkeypatch.setattr(_mod, "_INBOX",        vault / "00-Inbox")
    monkeypatch.setattr(_mod, "_INBOX_IMAGES", vault / "00-Inbox" / "images")
    monkeypatch.setattr(_mod, "_PROCESSING",   vault / "01-Processing")

    agent_state = tmp_path / ".agents" / "vision" / "state"
    agent_state.mkdir(parents=True)
    logs_dir = agent_state / "logs"
    logs_dir.mkdir()
    master_log = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
    master_log.parent.mkdir(parents=True)
    master_log.touch()
    shared_state = tmp_path / ".system" / "state"
    shared_state.mkdir(parents=True)
    signals_dir = tmp_path / ".agents" / "runtime" / "state" / "signals"
    signals_dir.mkdir(parents=True)

    monkeypatch.setattr(_mod, "_AGENT_STATE",  agent_state)
    monkeypatch.setattr(_mod, "_LOGS_DIR",     logs_dir)
    monkeypatch.setattr(_mod, "_MASTER_LOG",   master_log)
    monkeypatch.setattr(_mod, "_SHARED_STATE", shared_state)
    monkeypatch.setattr(_mod, "_PROC_IMAGES",  agent_state / "processed-images.json")
    monkeypatch.setattr(_mod, "_TOKEN_LINKS",  agent_state / "token-links.json")
    monkeypatch.setattr(_mod, "_QUEUE_FILE",   shared_state / "inbox-queue.json")
    monkeypatch.setattr(_mod, "_SIGNALS_DIR",  signals_dir)
    return vault


# ---------------------------------------------------------------------------
# _is_token
# ---------------------------------------------------------------------------

class TestIsToken:
    def test_non_png_is_not_token(self, tmp_path):
        jpg = tmp_path / "image.jpg"
        jpg.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        assert _mod._is_token(jpg) is False

    def test_missing_file_returns_false(self, tmp_path):
        assert _mod._is_token(tmp_path / "nope.png") is False

    def test_opaque_png_is_not_token(self, tmp_path):
        try:
            from PIL import Image
            img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
            p = tmp_path / "opaque.png"
            img.save(p)
            assert _mod._is_token(p) is False
        except ImportError:
            pytest.skip("Pillow not available")

    def test_transparent_corners_is_token(self, tmp_path):
        try:
            from PIL import Image
            img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
            img.putpixel((0, 0),   (0, 0, 0, 0))
            img.putpixel((63, 0),  (0, 0, 0, 0))
            img.putpixel((0, 63),  (0, 0, 0, 0))
            img.putpixel((63, 63), (0, 0, 0, 0))
            p = tmp_path / "token.png"
            img.save(p)
            assert _mod._is_token(p) is True
        except ImportError:
            pytest.skip("Pillow not available")

    def test_two_transparent_corners_is_token(self, tmp_path):
        """Spec says ≥2 transparent corners — two should be enough."""
        try:
            from PIL import Image
            img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
            img.putpixel((0, 0),  (0, 0, 0, 0))
            img.putpixel((63, 0), (0, 0, 0, 0))
            p = tmp_path / "two_corners.png"
            img.save(p)
            assert _mod._is_token(p) is True
        except ImportError:
            pytest.skip("Pillow not available")

    def test_one_transparent_corner_is_not_token(self, tmp_path):
        try:
            from PIL import Image
            img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
            img.putpixel((0, 0), (0, 0, 0, 0))
            p = tmp_path / "one_corner.png"
            img.save(p)
            assert _mod._is_token(p) is False
        except ImportError:
            pytest.skip("Pillow not available")


# ---------------------------------------------------------------------------
# _image_filename_slug
# ---------------------------------------------------------------------------

class TestImageFilenameSlug:
    def test_portrait_format(self):
        c = _clf(type_="portrait", ancestry="human", char_class="fighter", element="dark")
        slug = _mod._image_filename_slug(c)
        assert slug == "human-fighter-dark.portrait"

    def test_body_format(self):
        c = _clf(type_="body", ancestry="elf", char_class="wizard", element="light")
        slug = _mod._image_filename_slug(c)
        assert slug == "elf-wizard-light.body"

    def test_token_format(self):
        c = _clf(type_="token", ancestry="dwarf", char_class="cleric", element="none")
        slug = _mod._image_filename_slug(c)
        assert slug == "dwarf-cleric.token"

    def test_battlemap_format(self):
        c = _clf(type_="battlemap", ancestry="none", char_class="none", element="none", environment="dungeon")
        slug = _mod._image_filename_slug(c)
        assert slug == "battlemap-dungeon"

    def test_scene_format(self):
        c = _clf(type_="scene", ancestry="none", char_class="none", element="none", environment="forest")
        slug = _mod._image_filename_slug(c)
        assert slug == "scene-forest"

    def test_creature_type_fallback(self):
        c = _clf(type_="portrait", ancestry="none", char_class="none", creature_type="dragon", element="fire")
        slug = _mod._image_filename_slug(c)
        assert slug == "dragon-fire.portrait"

    def test_unknown_fallback_when_no_descriptors(self):
        c = _clf(type_="portrait", ancestry="none", char_class="none", element="none")
        slug = _mod._image_filename_slug(c)
        assert slug == "unknown.portrait"

    def test_battlemap_unknown_env(self):
        c = _clf(type_="battlemap", ancestry="none", char_class="none", element="none", environment="none")
        slug = _mod._image_filename_slug(c)
        assert slug == "battlemap-unknown"

    def test_slug_normalises_spaces(self):
        c = _clf(type_="portrait", ancestry="dark-elf", char_class="none", element="none")
        slug = _mod._image_filename_slug(c)
        assert " " not in slug


# ---------------------------------------------------------------------------
# _entity_slug
# ---------------------------------------------------------------------------

class TestEntitySlug:
    def test_portrait_prefix(self):
        c = _clf(type_="portrait", ancestry="human", char_class="fighter", element="dark")
        assert _mod._entity_slug(c) == "portrait-human-fighter-dark"

    def test_body_prefix(self):
        c = _clf(type_="body", ancestry="elf", char_class="wizard", element="none")
        assert _mod._entity_slug(c) == "body-elf-wizard"

    def test_token_prefix(self):
        c = _clf(type_="token", ancestry="orc", char_class="none", element="none")
        assert _mod._entity_slug(c) == "token-orc"

    def test_battlemap_with_env(self):
        c = _clf(type_="battlemap", ancestry="none", char_class="none", element="none", environment="dungeon")
        assert _mod._entity_slug(c) == "battlemap-dungeon"

    def test_scene_with_env(self):
        c = _clf(type_="scene", ancestry="none", char_class="none", element="none", environment="castle")
        assert _mod._entity_slug(c) == "scene-castle"

    def test_type_only_when_no_descriptors(self):
        c = _clf(type_="portrait", ancestry="none", char_class="none", element="none")
        assert _mod._entity_slug(c) == "portrait"


# ---------------------------------------------------------------------------
# _resolve_image_target
# ---------------------------------------------------------------------------

class TestResolveImageTarget:
    def test_returns_slug_path_when_no_collision(self, tmp_path):
        src    = tmp_path / "warrior.jpg"
        src.touch()
        target = _mod._resolve_image_target(src, "human-fighter-dark.portrait")
        assert target == tmp_path / "human-fighter-dark.portrait.jpg"

    def test_same_target_as_src_returns_target(self, tmp_path):
        src = tmp_path / "human-fighter-dark.portrait.jpg"
        src.touch()
        target = _mod._resolve_image_target(src, "human-fighter-dark.portrait")
        assert target == src

    def test_bumps_on_collision(self, tmp_path):
        src    = tmp_path / "warrior.jpg"
        src.touch()
        (tmp_path / "human-fighter-dark.portrait.jpg").touch()
        target = _mod._resolve_image_target(src, "human-fighter-dark.portrait")
        assert target.name == "human-fighter-dark.portrait-01.jpg"

    def test_bumps_twice(self, tmp_path):
        src = tmp_path / "warrior.jpg"
        src.touch()
        (tmp_path / "human-fighter-dark.portrait.jpg").touch()
        (tmp_path / "human-fighter-dark.portrait-01.jpg").touch()
        target = _mod._resolve_image_target(src, "human-fighter-dark.portrait")
        assert target.name == "human-fighter-dark.portrait-02.jpg"

    def test_preserves_extension(self, tmp_path):
        src = tmp_path / "map.webp"
        src.touch()
        target = _mod._resolve_image_target(src, "battlemap-dungeon")
        assert target.suffix == ".webp"


# ---------------------------------------------------------------------------
# _candidate_images
# ---------------------------------------------------------------------------

class TestCandidateImages:
    def test_returns_images_in_inbox(self, patch_roots, vault):
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        result = _mod._candidate_images({}, {})
        assert img in result

    def test_skips_processed_path(self, patch_roots, vault, tmp_path):
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        rel = img.relative_to(tmp_path).as_posix()
        state = {"version": 2, "images": {}, "pathIndex": {rel: "abc"}}
        result = _mod._candidate_images(state, {})
        assert img not in result

    def test_skips_queue_done(self, patch_roots, vault, tmp_path):
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        rel = img.relative_to(tmp_path).as_posix()
        queue = {rel: {"agents": {"vision": "done"}}}
        result = _mod._candidate_images({}, queue)
        assert img not in result

    def test_non_png_before_png(self, patch_roots, vault):
        jpg = vault / "00-Inbox" / "images" / "aaaa.jpg"
        png = vault / "00-Inbox" / "images" / "aaaa.png"
        jpg.touch()
        png.touch()
        result = _mod._candidate_images({}, {})
        jpg_idx = result.index(jpg)
        png_idx = result.index(png)
        assert jpg_idx < png_idx

    def test_skips_non_image_files(self, patch_roots, vault):
        txt = vault / "00-Inbox" / "images" / "notes.txt"
        txt.touch()
        result = _mod._candidate_images({}, {})
        assert txt not in result


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

class TestStateIO:
    def test_load_state_returns_default_when_missing(self, patch_roots):
        state = _mod._load_state()
        assert state["version"] == 2
        assert state["images"] == {}
        assert state["pathIndex"] == {}

    def test_save_and_reload_state(self, patch_roots):
        state = {"version": 2, "images": {"abc": {"path": "x"}}, "pathIndex": {"x": "abc"}}
        _mod._save_state(state)
        loaded = _mod._load_state()
        assert loaded["images"]["abc"]["path"] == "x"
        assert loaded["pathIndex"]["x"] == "abc"

    def test_save_is_atomic(self, patch_roots):
        state = {"version": 2, "images": {}, "pathIndex": {}}
        _mod._save_state(state)
        assert not _mod._PROC_IMAGES.with_suffix(".tmp").exists()


# ---------------------------------------------------------------------------
# Token links state I/O
# ---------------------------------------------------------------------------

class TestTokenLinks:
    def test_load_token_links_returns_empty_when_missing(self, patch_roots):
        links = _mod._load_token_links()
        assert links == {}

    def test_save_and_reload_token_links(self, patch_roots):
        links = {
            "abc123": {
                "tokenPath":    "knowledge-base/00-Inbox/images/A1/human-fighter.token.png",
                "sourcePath":   "knowledge-base/00-Inbox/images/A1/human-fighter.portrait.jpg",
                "sourceSha256": "def456",
                "linkedAt":     "2026-01-01T00:00:00+00:00",
            }
        }
        _mod._save_token_links(links)
        loaded = _mod._load_token_links()
        assert loaded["abc123"]["sourcePath"].endswith("portrait.jpg")

    def test_save_token_links_is_atomic(self, patch_roots):
        _mod._save_token_links({"x": {"tokenPath": "a", "sourcePath": "b", "sourceSha256": "c", "linkedAt": "t"}})
        assert not _mod._TOKEN_LINKS.with_suffix(".tmp").exists()


# ---------------------------------------------------------------------------
# _get_folder_candidates
# ---------------------------------------------------------------------------

class TestGetFolderCandidates:
    def _make_state(self, tmp_path, entries: list[dict]) -> dict:
        state: dict = {"version": 2, "images": {}, "pathIndex": {}}
        for e in entries:
            sha = e["sha"]
            rel = e["rel"]
            state["images"][sha] = {
                "path":          rel,
                "processedAt":   "2026-01-01T00:00:00+00:00",
                "originalName":  Path(rel).name,
                "type":          e.get("type", "portrait"),
                "ancestry":      e.get("ancestry", "human"),
                "class":         e.get("class", "fighter"),
                "creature_type": e.get("creature_type", "none"),
                "element":       e.get("element", "none"),
                "environment":   e.get("environment", "none"),
                "description":   e.get("description", ""),
                "sha256":        sha,
                "isToken":       e.get("isToken", False),
                "status":        e.get("status", "ok"),
            }
            state["pathIndex"][rel] = sha
        return state

    def test_returns_portrait_in_same_folder(self, patch_roots, vault, tmp_path):
        portrait = vault / "00-Inbox" / "images" / "A1" / "warrior.jpg"
        portrait.parent.mkdir(parents=True, exist_ok=True)
        portrait.touch()
        rel = portrait.relative_to(tmp_path).as_posix()
        state = self._make_state(tmp_path, [{"sha": "sha1", "rel": rel, "type": "portrait"}])
        result = _mod._get_folder_candidates(portrait.parent, state)
        assert portrait in result

    def test_excludes_token_type(self, patch_roots, vault, tmp_path):
        token = vault / "00-Inbox" / "images" / "A1" / "token.png"
        token.parent.mkdir(parents=True, exist_ok=True)
        token.touch()
        rel = token.relative_to(tmp_path).as_posix()
        state = self._make_state(tmp_path, [{"sha": "sha1", "rel": rel, "type": "token"}])
        result = _mod._get_folder_candidates(token.parent, state)
        assert token not in result

    def test_excludes_battlemap_type(self, patch_roots, vault, tmp_path):
        bmap = vault / "00-Inbox" / "images" / "A1" / "map.jpg"
        bmap.parent.mkdir(parents=True, exist_ok=True)
        bmap.touch()
        rel = bmap.relative_to(tmp_path).as_posix()
        state = self._make_state(tmp_path, [{"sha": "sha1", "rel": rel, "type": "battlemap"}])
        result = _mod._get_folder_candidates(bmap.parent, state)
        assert bmap not in result

    def test_excludes_different_folder(self, patch_roots, vault, tmp_path):
        portrait = vault / "00-Inbox" / "images" / "A2" / "warrior.jpg"
        portrait.parent.mkdir(parents=True, exist_ok=True)
        portrait.touch()
        other_folder = vault / "00-Inbox" / "images" / "A1"
        other_folder.mkdir(parents=True, exist_ok=True)
        rel = portrait.relative_to(tmp_path).as_posix()
        state = self._make_state(tmp_path, [{"sha": "sha1", "rel": rel, "type": "portrait"}])
        result = _mod._get_folder_candidates(other_folder, state)
        assert portrait not in result

    def test_excludes_failed_images(self, patch_roots, vault, tmp_path):
        portrait = vault / "00-Inbox" / "images" / "A1" / "corrupt.jpg"
        portrait.parent.mkdir(parents=True, exist_ok=True)
        portrait.touch()
        rel = portrait.relative_to(tmp_path).as_posix()
        state = self._make_state(tmp_path, [{"sha": "sha1", "rel": rel, "status": "failed"}])
        result = _mod._get_folder_candidates(portrait.parent, state)
        assert portrait not in result

    def test_excludes_path_prefix_keys(self, patch_roots, vault, tmp_path):
        portrait = vault / "00-Inbox" / "images" / "A1" / "corrupt.jpg"
        portrait.parent.mkdir(parents=True, exist_ok=True)
        portrait.touch()
        rel = portrait.relative_to(tmp_path).as_posix()
        # Store as failed path key
        state: dict = {"version": 2, "images": {}, "pathIndex": {rel: f"path:{rel}"}}
        result = _mod._get_folder_candidates(portrait.parent, state)
        assert portrait not in result


# ---------------------------------------------------------------------------
# _inherit_clf_from_state
# ---------------------------------------------------------------------------

class TestInheritClfFromState:
    def _entry(self, **overrides) -> dict:
        base = {
            "ancestry":      "human",
            "class":         "fighter",
            "creature_type": "none",
            "element":       "dark",
            "environment":   "none",
            "description":   "A weathered warrior.",
        }
        base.update(overrides)
        return base

    def test_type_is_always_token(self):
        clf = _mod._inherit_clf_from_state(self._entry())
        assert clf.type == ImageType.token

    def test_inherits_ancestry(self):
        clf = _mod._inherit_clf_from_state(self._entry(ancestry="elf"))
        assert clf.ancestry == "elf"

    def test_inherits_class(self):
        clf = _mod._inherit_clf_from_state(self._entry(**{"class": "wizard"}))
        assert clf.char_class == "wizard"

    def test_inherits_element(self):
        clf = _mod._inherit_clf_from_state(self._entry(element="fire"))
        assert clf.element == Element.fire

    def test_inherits_description(self):
        clf = _mod._inherit_clf_from_state(self._entry(description="A fierce paladin."))
        assert clf.description == "A fierce paladin."

    def test_defaults_to_none_values_when_missing(self):
        clf = _mod._inherit_clf_from_state({})
        assert clf.ancestry == "none"
        assert clf.char_class == "none"
        assert clf.element == Element.none


# ---------------------------------------------------------------------------
# _write_draft
# ---------------------------------------------------------------------------

class TestWriteDraft:
    def test_draft_has_required_frontmatter(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "human-fighter-dark.portrait.jpg"
        img.touch()
        out = vault / "01-Processing" / "portrait-human-fighter-dark.md"
        c = _clf()
        _mod._write_draft(out, c, img)
        raw = out.read_text(encoding="utf-8")
        fm_text = raw.split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm["status"] == "draft"
        assert fm["reviewed"] is False
        assert fm["quality"] == 0
        assert fm["type"] in ("npc", "location")

    def test_draft_body_has_description_section(self, patch_roots, vault, tmp_path):
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        out = vault / "01-Processing" / "portrait-human-fighter-dark.md"
        c = _clf(description="A grim swordsman with a scarred face.")
        _mod._write_draft(out, c, img)
        body = out.read_text(encoding="utf-8")
        assert "## Description" in body
        assert "A grim swordsman" in body

    def test_draft_sets_npc_type_for_portraits(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        out = vault / "01-Processing" / "portrait-human-fighter.md"
        _mod._write_draft(out, _clf(type_="portrait"), img)
        fm_text = out.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm["type"] == "npc"

    def test_draft_sets_location_type_for_battlemap(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "dungeon.jpg"
        img.touch()
        out = vault / "01-Processing" / "battlemap-dungeon.md"
        _mod._write_draft(out, _clf(type_="battlemap", environment="dungeon"), img)
        fm_text = out.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm["type"] == "location"

    def test_draft_never_sets_reviewed_true(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        out = vault / "01-Processing" / "portrait-human-fighter.md"
        _mod._write_draft(out, _clf(), img)
        fm_text = out.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm["reviewed"] is False

    def test_draft_includes_sha256_when_provided(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        out = vault / "01-Processing" / "portrait-human-fighter.md"
        _mod._write_draft(out, _clf(), img, sha256="deadbeef" * 8)
        fm_text = out.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert fm.get("sha256") == "deadbeef" * 8

    def test_draft_omits_sha256_when_not_provided(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        out = vault / "01-Processing" / "portrait-human-fighter.md"
        _mod._write_draft(out, _clf(), img)
        fm_text = out.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert "sha256" not in fm


# ---------------------------------------------------------------------------
# Failed image storage
# ---------------------------------------------------------------------------

class TestFailedImageStorage:
    def test_failed_image_stored_with_path_prefix_key(self, patch_roots, vault, tmp_path):
        img = vault / "00-Inbox" / "images" / "corrupt.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        rel = img.relative_to(tmp_path).as_posix()

        state = _mod._load_state()
        sha = _mod._sha256(img)
        state["images"][f"path:{rel}"] = {
            "path": rel, "processedAt": "2026-01-01T00:00:00Z",
            "originalName": img.name, "type": "unknown",
            "ancestry": "none", "class": "none",
            "creature_type": "none", "element": "none",
            "environment": "none", "description": "",
            "sha256": sha, "isToken": False, "status": "failed",
        }
        state["pathIndex"][rel] = f"path:{rel}"
        _mod._save_state(state)

        loaded = _mod._load_state()
        assert f"path:{rel}" in loaded["images"]
        assert loaded["images"][f"path:{rel}"]["status"] == "failed"
        assert loaded["pathIndex"][rel] == f"path:{rel}"

    def test_failed_image_excluded_from_candidates(self, patch_roots, vault, tmp_path):
        img = vault / "00-Inbox" / "images" / "corrupt.jpg"
        img.touch()
        rel = img.relative_to(tmp_path).as_posix()
        state = {
            "version": 2,
            "images": {},
            "pathIndex": {rel: f"path:{rel}"},
        }
        result = _mod._candidate_images(state, {})
        assert img not in result


# ---------------------------------------------------------------------------
# Signal emission
# ---------------------------------------------------------------------------

class TestSignalEmission:
    def test_emits_image_classified_signal(self, patch_roots, tmp_path):
        from shared.signal_bus import SignalConsumer
        signals_dir = tmp_path / ".agents" / "runtime" / "state" / "signals"

        with patch.object(_mod, "LLMClient") as MockClient:
            client = MockClient.return_value
            client.is_available.return_value = True
            client.vision_chat.return_value = {
                "type": "portrait", "ancestry": "human", "class": "fighter",
                "creature_type": "none", "element": "dark", "environment": "none",
                "description": "A warrior.",
            }

            img = (
                (patch_roots if hasattr(patch_roots, "__truediv__") else
                 _mod._VAULT_ROOT)
                / "00-Inbox" / "images" / "warrior.jpg"
            )
            img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)

            with patch.object(_mod, "_PROMPT_FILE", patch_roots / "noprompt.txt" if False else _mod._PROMPT_FILE):
                import contextlib, io as _io, sys as _sys
                buf = _io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf):
                        _mod.main()
                except SystemExit:
                    pass

        consumer = SignalConsumer(signals_dir)
        signals = consumer.pending("image-classified")
        assert len(signals) >= 1
        assert signals[0]["emitter"] == "vision-agent"


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

class TestToolsDefinition:
    def test_required_tools_present(self):
        names = {t["name"] for t in _mod.TOOLS}
        assert "list_pending_images" in names
        assert "detect_token"        in names
        assert "match_token_face"    in names
        assert "classify_image"      in names
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

    def test_match_token_face_has_image_path_param(self):
        tool = next(t for t in _mod.TOOLS if t["name"] == "match_token_face")
        props = tool["input_schema"]["properties"]
        assert "image_path" in props


# ---------------------------------------------------------------------------
# _resolve_entity_path
# ---------------------------------------------------------------------------

class TestResolveEntityPath:
    def test_returns_slug_md_when_no_collision(self, patch_roots, vault):
        path = _mod._resolve_entity_path("portrait-human-fighter-dark")
        assert path == vault / "01-Processing" / "portrait-human-fighter-dark.md"

    def test_bumps_on_collision(self, patch_roots, vault):
        (vault / "01-Processing" / "portrait-human-fighter-dark.md").touch()
        path = _mod._resolve_entity_path("portrait-human-fighter-dark")
        assert path.name == "portrait-human-fighter-dark-01.md"

    def test_bumps_twice(self, patch_roots, vault):
        (vault / "01-Processing" / "portrait-human-fighter-dark.md").touch()
        (vault / "01-Processing" / "portrait-human-fighter-dark-01.md").touch()
        path = _mod._resolve_entity_path("portrait-human-fighter-dark")
        assert path.name == "portrait-human-fighter-dark-02.md"

    def test_creates_processing_dir_if_missing(self, patch_roots, vault):
        import shutil
        shutil.rmtree(vault / "01-Processing")
        path = _mod._resolve_entity_path("battlemap-dungeon")
        assert path.parent.exists()


# ---------------------------------------------------------------------------
# _rename_image
# ---------------------------------------------------------------------------

class TestRenameImage:
    def test_renames_to_canonical_slug(self, patch_roots, vault):
        img = vault / "00-Inbox" / "images" / "A1" / "warrior.jpg"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        c = _clf(type_="portrait", ancestry="human", char_class="fighter", element="dark")
        new_path = _mod._rename_image(img, c)
        assert new_path.name == "human-fighter-dark.portrait.jpg"
        assert new_path.exists()
        assert not img.exists()

    def test_no_rename_when_already_canonical(self, patch_roots, vault):
        img = vault / "00-Inbox" / "images" / "A1" / "human-fighter-dark.portrait.jpg"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        c = _clf(type_="portrait", ancestry="human", char_class="fighter", element="dark")
        new_path = _mod._rename_image(img, c)
        assert new_path == img

    def test_bumps_colliding_slug(self, patch_roots, vault):
        folder = vault / "00-Inbox" / "images" / "A1"
        folder.mkdir(parents=True, exist_ok=True)
        existing = folder / "human-fighter-dark.portrait.jpg"
        existing.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        src = folder / "warrior_v2.jpg"
        src.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        c = _clf(type_="portrait", ancestry="human", char_class="fighter", element="dark")
        new_path = _mod._rename_image(src, c)
        assert new_path.name == "human-fighter-dark.portrait-01.jpg"


# ---------------------------------------------------------------------------
# call_tool dispatch
# ---------------------------------------------------------------------------

class TestCallTool:
    def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            _mod.call_tool("no_such_tool", {}, {"project_root": "/tmp"})

    def test_list_pending_images_returns_json_list(self, patch_roots, vault):
        result = _mod.call_tool("list_pending_images", {}, {"project_root": str(vault.parent)})
        data = json.loads(result)
        assert isinstance(data, list)

    def test_detect_token_missing_file(self, tmp_path):
        result = _mod.call_tool(
            "detect_token",
            {"image_path": str(tmp_path / "nope.png")},
            {"project_root": str(tmp_path)},
        )
        data = json.loads(result)
        assert data["is_token"] is False

    def test_match_token_face_missing_file_returns_error(self, patch_roots, tmp_path):
        result = _mod.call_tool(
            "match_token_face",
            {"image_path": str(tmp_path / "nope.png")},
            {"project_root": str(tmp_path)},
        )
        data = json.loads(result)
        assert "error" in data

    def test_match_token_face_no_candidates_returns_not_matched(self, patch_roots, tmp_path):
        p = tmp_path / "token.png"
        p.write_bytes(b"\x89PNG" + b"\x00" * 64)
        result = _mod.call_tool(
            "match_token_face",
            {"image_path": str(p)},
            {"project_root": str(tmp_path)},
        )
        data = json.loads(result)
        assert data["matched"] is False
        assert "candidates_checked" in data

    def test_classify_image_returns_error_when_file_missing(self, patch_roots, tmp_path):
        result = _mod.call_tool(
            "classify_image",
            {"image_path": str(tmp_path / "nope.jpg")},
            {"project_root": str(tmp_path)},
        )
        data = json.loads(result)
        assert "error" in data

    def test_classify_image_returns_error_when_llm_offline(self, patch_roots, tmp_path):
        img = tmp_path / "warrior.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        with patch.object(_mod, "LLMClient") as MockClient:
            MockClient.return_value.is_available.return_value = False
            result = _mod.call_tool(
                "classify_image",
                {"image_path": str(img)},
                {"project_root": str(tmp_path)},
            )
        data = json.loads(result)
        assert "error" in data

    def test_classify_image_returns_classification_when_llm_available(self, patch_roots, tmp_path):
        img = tmp_path / "warrior.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        with patch.object(_mod, "LLMClient") as MockClient:
            client = MockClient.return_value
            client.is_available.return_value = True
            client.vision_chat.return_value = {
                "type": "portrait", "ancestry": "human", "class": "fighter",
                "creature_type": "none", "element": "dark", "environment": "none",
                "description": "A warrior.",
            }
            result = _mod.call_tool(
                "classify_image",
                {"image_path": str(img)},
                {"project_root": str(tmp_path)},
            )
        data = json.loads(result)
        assert data["type"] == "portrait"
        assert data["ancestry"] == "human"
        assert "is_token" in data
