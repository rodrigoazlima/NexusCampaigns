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
from nexus.shared.models import Element, Environment, ImageType, VisionClassification


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
    candidate_tags: list[str] | None = None,
) -> VisionClassification:
    return VisionClassification(
        type=ImageType(type_),
        ancestry=ancestry,
        **{"class": char_class},
        creature_type=creature_type,
        element=Element(element),
        environment=Environment(environment),
        description=description,
        candidate_tags=candidate_tags or [],
    )


# ---------------------------------------------------------------------------
# Vault layout fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    kb = tmp_path / ".knowledge-base"
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

    agent_state = tmp_path / "agents" / "vision" / "state"
    agent_state.mkdir(parents=True)
    logs_dir = agent_state / "logs"
    logs_dir.mkdir()
    master_log = tmp_path / "agents" / "runtime" / "state" / "logs" / "automation.log"
    master_log.parent.mkdir(parents=True)
    master_log.touch()
    shared_state = tmp_path / "system" / "state"
    shared_state.mkdir(parents=True)
    signals_dir = tmp_path / "agents" / "runtime" / "state" / "signals"
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
# _extract_candidate_tags
# ---------------------------------------------------------------------------

class TestExtractCandidateTags:
    def test_harvests_equipment_weapons(self):
        raw = {"visual_analysis": {"equipment": {"weapons": ["Axe"], "shield": [], "other": []}}}
        assert "axe" in _mod._extract_candidate_tags(raw)

    def test_harvests_multiple_sections(self):
        raw = {
            "visual_analysis": {
                "equipment": {"weapons": ["sword"]},
                "clothing": {"materials": ["leather"]},
                "fantasy_features": {"creatures": ["wolf"]},
            }
        }
        tags = _mod._extract_candidate_tags(raw)
        assert set(tags) == {"sword", "leather", "wolf"}

    def test_normalizes_case_and_whitespace(self):
        raw = {"visual_analysis": {"equipment": {"weapons": ["  Battle Axe  "]}}}
        assert _mod._extract_candidate_tags(raw) == ["battle axe"]

    def test_dedupes_preserving_order(self):
        raw = {
            "visual_analysis": {
                "equipment": {"weapons": ["axe"], "tools": ["Axe"]},
            }
        }
        assert _mod._extract_candidate_tags(raw) == ["axe"]

    def test_drops_empty_and_non_string_items(self):
        raw = {"visual_analysis": {"equipment": {"weapons": ["", "  ", "axe", 5, None]}}}
        assert _mod._extract_candidate_tags(raw) == ["axe"]

    def test_missing_visual_analysis_returns_empty(self):
        assert _mod._extract_candidate_tags({}) == []

    def test_malformed_shape_returns_empty_not_raises(self):
        raw = {"visual_analysis": {"equipment": "not-a-dict"}}
        assert _mod._extract_candidate_tags(raw) == []

    def test_ignores_non_candidate_sections(self):
        raw = {"visual_analysis": {"lighting": {"rim_lighting": True}, "composition": {"shot_type": "wide"}}}
        assert _mod._extract_candidate_tags(raw) == []

    def test_drops_sentence_length_pseudo_tag(self):
        """The LLM sometimes ignores the '1-3 word tag' instruction and
        returns a full descriptive sentence as one array item - that must
        not land in frontmatter tags: as if it were a real tag."""
        sentence = (
            "a large sword with a black blade and hilt, featuring white "
            "geometric patterns on the blade and a rectangular guard"
        )
        raw = {"visual_analysis": {"equipment": {"weapons": [sentence, "black blade"]}}}
        tags = _mod._extract_candidate_tags(raw)
        assert sentence not in tags
        assert "black blade" in tags


class TestIsConcreteTag:
    def test_accepts_short_tags(self):
        assert _mod._is_concrete_tag("sword")
        assert _mod._is_concrete_tag("stylized sword")
        assert _mod._is_concrete_tag("rectangular guard")

    def test_rejects_empty(self):
        assert not _mod._is_concrete_tag("")

    def test_rejects_sentence_length(self):
        assert not _mod._is_concrete_tag(
            "a large sword with a black blade and hilt, featuring white geometric patterns"
        )

    def test_boundary_at_max_words(self):
        six = "one two three four five six"
        seven = six + " seven"
        assert _mod._is_concrete_tag(six)
        assert not _mod._is_concrete_tag(seven)


# ---------------------------------------------------------------------------
# _classify_one
# ---------------------------------------------------------------------------

def _write_real_jpg(path):
    """A real (tiny) JPEG - _image_content_block PIL-opens the file, so fake
    bytes crash it."""
    from PIL import Image
    Image.new("RGB", (8, 8), (128, 64, 32)).save(path, format="JPEG")


# The 4 required steps (see classify_images.py's _STEP_PROMPT_FILES) plus
# the 3 optional follow-up cycles - 7 client.chat() calls in the happy path.
_STEP1_JSON = json.dumps({"type": "scene"})
_STEP2_JSON = json.dumps({
    "visual_analysis": {"equipment": {"weapons": ["axe"], "shield": [], "other": []}},
})
_STEP3_JSON = json.dumps({"environment": "interior", "element": "none"})
_STEP4_JSON = json.dumps({"description": "An axe on a table."})
_CYCLE2_JSON = json.dumps({"category": "scene", "additional_tags": ["steel", "wood"]})
_CYCLE3_JSON = json.dumps({"entity_type": "item", "additional_tags": ["blade"]})
_CYCLE4_JSON = json.dumps({
    "final_tags": ["axe", "steel", "wood", "blade", "weapon", "iron"],
    "entity_type": "item",
})
_FULL_RUN_RESPONSES = [_STEP1_JSON, _STEP2_JSON, _STEP3_JSON, _STEP4_JSON, _CYCLE2_JSON, _CYCLE3_JSON, _CYCLE4_JSON]

_STEP_PROMPTS = {
    "type": "step1", "visual": "step2",
    "pf2e_character": "step3-character", "pf2e_environment": "step3-environment",
    "description": "step4",
}


class TestClassifyImageFull:
    @pytest.fixture(autouse=True)
    def _no_retry_backoff(self, monkeypatch):
        # Required-step retries sleep _STEP_RETRY_BACKOFF_S between attempts -
        # zero it out so a test that exhausts retries doesn't actually wait.
        monkeypatch.setattr(_mod, "_STEP_RETRY_BACKOFF_S", 0)

    def test_full_seven_step_run(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        client.chat.side_effect = list(_FULL_RUN_RESPONSES)

        clf = _mod.classify_image_full(img, client, _STEP_PROMPTS, is_tk=False)

        assert clf.type == ImageType.scene
        assert clf.entity_type == "item"
        assert clf.candidate_tags == ["axe", "steel", "wood", "blade", "weapon", "iron"]
        assert len(clf.candidate_tags) >= _mod._MIN_TAGS_TARGET
        assert client.chat.call_count == 7

    def test_conversation_never_exceeds_message_cap(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        seen_lengths = []
        responses = list(_FULL_RUN_RESPONSES)

        def _chat(messages, **kwargs):
            seen_lengths.append(len(messages))
            return responses[len(seen_lengths) - 1]

        client.chat.side_effect = _chat
        _mod.classify_image_full(img, client, _STEP_PROMPTS, is_tk=False)

        # each call's message list + its reply must stay within the cap
        assert all(n + 1 <= _mod._MAX_CONVERSATION_MESSAGES for n in seen_lengths)

    def test_later_cycle_parse_failure_keeps_prior_values(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        # required steps 1-4 all succeed; the 3 optional cycles all fail to
        # parse and must degrade gracefully instead of raising
        client.chat.side_effect = [
            _STEP1_JSON, _STEP2_JSON, _STEP3_JSON, _STEP4_JSON,
            "not json", "still not json", "nope",
        ]

        clf = _mod.classify_image_full(img, client, _STEP_PROMPTS, is_tk=False)

        # required steps' harvest survives; failed optional cycles degrade
        assert clf.type == ImageType.scene
        assert "axe" in clf.candidate_tags
        assert clf.entity_type == "none"

    def test_required_step_error_propagates_after_retries(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        client.chat.return_value = "not json at all"

        with pytest.raises(Exception):
            _mod.classify_image_full(img, client, _STEP_PROMPTS, is_tk=False)
        # initial attempt + _STEP_MAX_RETRIES retries, all on step 1
        assert client.chat.call_count == _mod._STEP_MAX_RETRIES + 1

    def test_token_flag_pins_type_against_cycle2(self, tmp_path):
        img = tmp_path / "tok.png"
        _write_real_jpg(img)

        client = MagicMock()
        client.chat.side_effect = list(_FULL_RUN_RESPONSES)

        clf = _mod.classify_image_full(img, client, _STEP_PROMPTS, is_tk=True)
        assert clf.type == ImageType.token  # cycle 2's "scene" must not un-pin a token


class TestParseJsonResponse:
    def test_plain_json(self):
        assert _mod._parse_json_response('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert _mod._parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fence_without_language(self):
        assert _mod._parse_json_response('```\n{"a": 1}\n```') == {"a": 1}

    def test_invalid_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _mod._parse_json_response("not json")


class TestRefineTagsWithLibrary:
    _LIBRARY = {"tags": {
        "elf": {"createdAt": "t", "count": 5, "aliases": []},
        "axe": {"createdAt": "t", "count": 2, "aliases": []},
    }}

    def test_fresh_conversation(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        client.chat.return_value = json.dumps(
            {"final_tags": ["axe", "weapon"], "entity_type": "item"}
        )

        tags, et = _mod.refine_tags_with_library(
            img, client, ["axe"], "none", self._LIBRARY
        )
        assert tags == ["axe", "weapon"]
        assert et == "item"
        # fresh conversation: system + user(image+prompt)
        sent = client.chat.call_args[0][0]
        assert sent[0]["role"] == "system"
        assert len(sent) == 3  # + appended assistant reply

    def test_extends_existing_history(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "c1"},
            {"role": "assistant", "content": "r1"},
        ]
        client = MagicMock()
        client.chat.return_value = json.dumps({"final_tags": ["axe"], "entity_type": "item"})

        _mod.refine_tags_with_library(img, client, ["axe"], "none", self._LIBRARY, history=history)
        # in-conversation: appended user turn + assistant reply onto the same list
        assert len(history) == 5

    def test_over_budget_history_returns_inputs_unchanged(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        history = [{"role": "user", "content": f"m{i}"} for i in range(_mod._MAX_CONVERSATION_MESSAGES)]
        client = MagicMock()

        tags, et = _mod.refine_tags_with_library(
            img, client, ["axe"], "item", self._LIBRARY, history=history
        )
        assert tags == ["axe"]
        assert et == "item"
        client.chat.assert_not_called()

    def test_parse_failure_returns_inputs(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        client.chat.return_value = "garbage"

        tags, et = _mod.refine_tags_with_library(img, client, ["axe"], "item", self._LIBRARY)
        assert tags == ["axe"]
        assert et == "item"

    def test_invalid_entity_type_rejected(self, tmp_path):
        img = tmp_path / "axe.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        client.chat.return_value = json.dumps(
            {"final_tags": ["axe"], "entity_type": "not-a-real-type"}
        )

        _, et = _mod.refine_tags_with_library(img, client, ["axe"], "item", self._LIBRARY)
        assert et == "item"  # unrecognized value keeps the hint

    def test_final_tags_merge_not_replace(self, tmp_path):
        """Cycle 4 must never silently drop a tag an earlier cycle already
        grounded in the image's own visual_analysis - a model that rephrases
        ("weapon" -> "stylized sword") instead of listing both would
        otherwise erase "weapon" from the note entirely."""
        img = tmp_path / "sword.jpg"
        _write_real_jpg(img)

        client = MagicMock()
        client.chat.return_value = json.dumps(
            {"final_tags": ["stylized sword"], "entity_type": "item"}
        )

        tags, et = _mod.refine_tags_with_library(
            img, client, ["weapon", "black blade"], "item", self._LIBRARY
        )
        assert "weapon" in tags
        assert "black blade" in tags
        assert "stylized sword" in tags
        assert et == "item"

    def test_final_tags_drop_sentence_length_candidate(self, tmp_path):
        img = tmp_path / "sword.jpg"
        _write_real_jpg(img)

        sentence = "a large sword with a black blade and hilt featuring white geometric patterns"
        client = MagicMock()
        client.chat.return_value = json.dumps(
            {"final_tags": [sentence, "weapon"], "entity_type": "item"}
        )

        tags, _ = _mod.refine_tags_with_library(img, client, ["axe"], "item", self._LIBRARY)
        assert sentence not in tags
        assert "weapon" in tags


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
        """Spec says ≥2 transparent corners - two should be enough."""
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

    def test_scene_with_item_entity_type_uses_entity_slug(self):
        """A sword closeup with no readable environment: type=scene (no
        'isolated object' option exists), entity_type=item. Must not fall
        into the generic scene-{environment} bucket."""
        c = _clf(type_="scene", environment="interior", candidate_tags=["stylized sword", "weapon"])
        c = c.model_copy(update={"entity_type": "item"})
        slug = _mod._image_filename_slug(c)
        assert slug == "item-stylized-sword"

    def test_scene_with_place_entity_type_keeps_environment_slug(self):
        """entity_type=location is place-like - the scene bucket is correct
        here, no override should trigger."""
        c = _clf(type_="scene", environment="forest")
        c = c.model_copy(update={"entity_type": "location"})
        slug = _mod._image_filename_slug(c)
        assert slug == "scene-forest"

    def test_scene_object_with_no_tags_falls_back_to_environment(self):
        c = _clf(type_="scene", environment="interior", candidate_tags=[])
        c = c.model_copy(update={"entity_type": "artifact"})
        slug = _mod._image_filename_slug(c)
        assert slug == "artifact-interior"


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

    def test_battlemap_object_entity_type_uses_entity_slug(self):
        c = _clf(type_="battlemap", environment="dungeon", candidate_tags=["ancient statue"])
        c = c.model_copy(update={"entity_type": "artifact"})
        assert _mod._entity_slug(c) == "artifact-ancient-statue"

    def test_two_unrelated_object_photos_do_not_collide(self):
        """The bug this whole override exists to fix: two different sword
        photos, same type=scene/environment=interior, must not resolve to
        the same slug (which would collision-bump into a meaningless
        scene-interior/-01/-02 family instead of reflecting either image)."""
        a = _clf(type_="scene", environment="interior", candidate_tags=["black blade sword"])
        a = a.model_copy(update={"entity_type": "item"})
        b = _clf(type_="scene", environment="interior", candidate_tags=["trident blade sword"])
        b = b.model_copy(update={"entity_type": "item"})
        assert _mod._entity_slug(a) != _mod._entity_slug(b)


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
                "tokenPath":    ".knowledge-base/00-Inbox/images/A1/human-fighter.token.png",
                "sourcePath":   ".knowledge-base/00-Inbox/images/A1/human-fighter.portrait.jpg",
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

    def test_draft_merges_candidate_tags_into_tags_not_as_field(self, patch_roots, vault, tmp_path):
        """The multi-cycle conversation's final tags land in the note's `tags:`
        (they're already library-aligned by cycle 4) - but never as a separate
        `candidate_tags:` frontmatter field."""
        import yaml
        img = vault / "00-Inbox" / "images" / "warrior.jpg"
        img.touch()
        out = vault / "01-Processing" / "portrait-human-fighter.md"
        _mod._write_draft(out, _clf(candidate_tags=["axe", "steel"]), img)
        fm_text = out.read_text(encoding="utf-8").split("---")[1]
        fm = yaml.safe_load(fm_text)
        assert "candidate_tags" not in fm
        assert "axe" in fm["tags"]
        assert "steel" in fm["tags"]

    def test_draft_prefers_grounded_entity_type(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "axe.jpg"
        img.touch()
        out = vault / "01-Processing" / "scene-interior.md"
        c = _clf(type_="scene", environment="interior")
        c = c.model_copy(update={"entity_type": "item"})
        _mod._write_draft(out, c, img)
        fm = yaml.safe_load(out.read_text(encoding="utf-8").split("---")[1])
        assert fm["type"] == "item"

    def test_draft_falls_back_to_placeholder_type_when_none(self, patch_roots, vault, tmp_path):
        import yaml
        img = vault / "00-Inbox" / "images" / "axe.jpg"
        img.touch()
        out = vault / "01-Processing" / "scene-interior.md"
        _mod._write_draft(out, _clf(type_="scene", environment="interior"), img)
        fm = yaml.safe_load(out.read_text(encoding="utf-8").split("---")[1])
        assert fm["type"] == "location"

    def test_draft_uses_item_body_for_object_in_scene_bucket(self, patch_roots, vault, tmp_path):
        """A sword photographed with no readable environment lands on
        type=scene/entity_type=item - the body must not claim '**Type**:
        Scene' (the old bug: frontmatter said item, body said Scene) and
        must use the item body's own sections instead of scene's Atmosphere/
        Story Hooks template."""
        img = vault / "00-Inbox" / "images" / "sword.jpg"
        img.touch()
        out = vault / "01-Processing" / "item-sword.md"
        c = _clf(type_="scene", environment="interior", candidate_tags=["stylized sword", "weapon"])
        c = c.model_copy(update={"entity_type": "item"})
        _mod._write_draft(out, c, img)
        body = out.read_text(encoding="utf-8")
        assert "**Type**: Scene" not in body
        assert "**Type**: Item" in body
        assert "## Visual Details" in body
        assert "stylized sword" in body

    def test_draft_uses_scene_body_when_entity_type_is_place_like(self, patch_roots, vault, tmp_path):
        img = vault / "00-Inbox" / "images" / "dungeon.jpg"
        img.touch()
        out = vault / "01-Processing" / "scene-dungeon.md"
        c = _clf(type_="scene", environment="dungeon")
        c = c.model_copy(update={"entity_type": "location"})
        _mod._write_draft(out, c, img)
        body = out.read_text(encoding="utf-8")
        assert "**Type**: Scene" in body
        assert "## Story Hooks" in body


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
        from nexus.shared.signal_bus import SignalConsumer
        signals_dir = tmp_path / "agents" / "runtime" / "state" / "signals"

        with patch.object(_mod, "LLMClient") as MockClient:
            client = MockClient.return_value
            client.is_available.return_value = True
            # Same canned reply for every required step (type/visual/pf2e/
            # description) and every optional cycle - satisfies each step's
            # validation (type is a valid structural type, visual_analysis
            # is a dict, description is non-empty) without needing a
            # per-call side_effect list.
            client.chat.return_value = json.dumps({
                "type": "portrait", "ancestry": "human", "class": "fighter",
                "creature_type": "none", "element": "dark", "environment": "none",
                "description": "A warrior.", "visual_analysis": {},
            })

            img = (
                (patch_roots if hasattr(patch_roots, "__truediv__") else
                 _mod._VAULT_ROOT)
                / "00-Inbox" / "images" / "warrior.jpg"
            )
            _write_real_jpg(img)

            import contextlib, io as _io
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
        _write_real_jpg(img)
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
        _write_real_jpg(img)
        with patch.object(_mod, "LLMClient") as MockClient:
            client = MockClient.return_value
            client.is_available.return_value = True
            client.chat.return_value = json.dumps({
                "type": "portrait", "ancestry": "human", "class": "fighter",
                "creature_type": "none", "element": "dark", "environment": "none",
                "description": "A warrior.", "visual_analysis": {},
            })
            result = _mod.call_tool(
                "classify_image",
                {"image_path": str(img)},
                {"project_root": str(tmp_path)},
            )
        data = json.loads(result)
        assert data["type"] == "portrait"
        assert data["ancestry"] == "human"
        assert "is_token" in data
