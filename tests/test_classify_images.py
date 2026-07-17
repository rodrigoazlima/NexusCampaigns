"""
Pure-logic unit tests for 06-classify-images pipeline.

Mirrors the PowerShell helper functions in Python so tests run without
PowerShell, LM Studio, or System.Drawing. All assertions operate on file
state (input images → output files); no subprocess calls here.

Complements tests/test_06_classify_images.py (subprocess integration layer).

Requirements: pytest, Pillow, numpy, scikit-image (optional, used for SSIM).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Generator

import pytest

try:
    import numpy as np
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from skimage.metrics import structural_similarity as ssim

    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False

pytestmark = pytest.mark.skipif(not HAS_PIL, reason="Pillow + numpy required")


# ---------------------------------------------------------------------------
# Image comparison helpers
# ---------------------------------------------------------------------------


def images_are_equal(path_a: Path, path_b: Path) -> bool:
    """Pixel-accurate comparison of two image files.

    Both images are normalised to RGBA before comparison so format differences
    (RGB vs RGBA) do not produce false negatives for visually identical images.
    """
    img_a = Image.open(path_a).convert("RGBA")
    img_b = Image.open(path_b).convert("RGBA")
    if img_a.size != img_b.size:
        return False
    return bool(np.array_equal(np.array(img_a), np.array(img_b)))


def assert_images_similar(
    path_a: Path, path_b: Path, min_ssim: float = 0.95
) -> None:
    """Assert perceptual similarity via SSIM (grayscale channel).

    Resizes *path_b* to match *path_a* dimensions before comparison so tests
    survive minor resampling artefacts introduced by format round-trips.

    Raises AssertionError if SSIM < *min_ssim*.
    """
    if not HAS_SKIMAGE:
        pytest.skip("scikit-image not available - SSIM test skipped")

    gray_a = np.array(Image.open(path_a).convert("L"))
    gray_b_img = Image.open(path_b).convert("L")
    if gray_b_img.size != (gray_a.shape[1], gray_a.shape[0]):
        gray_b_img = gray_b_img.resize(
            (gray_a.shape[1], gray_a.shape[0]), Image.LANCZOS
        )
    gray_b = np.array(gray_b_img)
    score: float = ssim(gray_a, gray_b, data_range=255)
    assert score >= min_ssim, (
        f"SSIM {score:.4f} < {min_ssim} - images are not sufficiently similar\n"
        f"  A: {path_a}\n  B: {path_b}"
    )


# ---------------------------------------------------------------------------
# Image fixture factories
# ---------------------------------------------------------------------------


def _solid_rgb(path: Path, size: tuple[int, int] = (64, 64), color: tuple[int, int, int] = (120, 80, 200)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _token_png(path: Path, size: tuple[int, int] = (64, 64)) -> Path:
    """RGBA PNG whose 8 corner/edge-midpoint pixels are fully transparent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", size, (150, 100, 50, 255))
    px = img.load()
    w, h = size
    for x, y in [
        (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
        (w // 2, 0), (0, h // 2), (w - 1, h // 2), (w // 2, h - 1),
    ]:
        px[x, y] = (0, 0, 0, 0)
    img.save(path, "PNG")
    return path


# ---------------------------------------------------------------------------
# Python mirror: token detection
# ---------------------------------------------------------------------------

_SAMPLE_POINTS_RATIO = [
    (0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0),
    (0.5, 0.0), (0.0, 0.5), (1.0, 0.5), (0.5, 1.0),
]


def detect_token(image_path: Path) -> bool:
    """Python mirror of PS Test-IsToken.

    Returns True iff image is PNG with ≥2 of 8 sampled corner/edge points
    having alpha < 128.
    """
    if image_path.suffix.lower() != ".png":
        return False
    img = Image.open(image_path)
    if img.mode not in ("RGBA", "LA", "PA"):
        return False
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    w, h = img.size
    transparent = sum(
        1
        for rx, ry in _SAMPLE_POINTS_RATIO
        if img.getpixel((int(rx * (w - 1)), int(ry * (h - 1))))[3] < 128
    )
    return transparent >= 2


# ---------------------------------------------------------------------------
# Python mirror: filename slug builder
# ---------------------------------------------------------------------------


def build_slug(
    type_: str,
    race: str = "none",
    class_: str = "none",
    element: str = "none",
    environment: str = "none",
    is_token: bool = False,
    ext: str = ".jpg",
) -> str:
    """Python mirror of the slug-building logic in Resolve-TargetFilename."""
    if type_ in ("battlemap", "scene"):
        return f"{type_}-{environment}{ext}"
    if is_token:
        return f"{race}-{class_}-{element}.token{ext}"
    return f"{race}-{class_}-{element}.{type_}{ext}"


# ---------------------------------------------------------------------------
# Python mirror: LLM response normaliser
# ---------------------------------------------------------------------------

_VALID_TYPES = frozenset({"portrait", "body", "battlemap", "scene"})
_VALID_RACES = frozenset({
    "human", "elf", "dark-elf", "dwarf", "orc", "goblin", "troll", "ogre",
    "dragon", "angel", "devil", "demon", "undead", "skeleton", "zombie",
    "vampire", "werewolf", "spirit",
})
_VALID_CLASSES = frozenset({
    "warrior", "mage", "archer", "cleric", "paladin", "necromancer",
    "assassin", "monster", "none",
})
_VALID_ELEMENTS = frozenset({"fire", "water", "earth", "air", "nature", "dark", "light", "none"})
_VALID_ENVIRONMENTS = frozenset({
    "dungeon", "cave", "forest", "city", "tavern", "desert", "snow", "sea",
    "swamp", "ruins", "temple", "castle", "plains", "mountain",
    "interior", "exterior", "none",
})


def normalise_llm(raw: dict) -> dict:
    """Python mirror of the PS sanitisation logic inside Invoke-VisionLLM."""
    type_  = raw.get("type", "")
    race   = raw.get("race", "none")
    class_ = raw.get("class", "none")
    elem   = raw.get("element", "none")
    env    = raw.get("environment", "none")

    type_  = type_  if type_  in _VALID_TYPES        else "portrait"
    race   = race   if (race  == "none" or race  in _VALID_RACES)   else "unknown"
    class_ = class_ if (class_ == "none" or class_ in _VALID_CLASSES) else "none"
    elem   = elem   if (elem  == "none" or elem  in _VALID_ELEMENTS) else "none"
    env    = env    if env    in _VALID_ENVIRONMENTS else "none"

    if type_ in ("battlemap", "scene"):
        race = class_ = elem = "none"

    return {"type": type_, "race": race, "class": class_, "element": elem, "environment": env}


# ---------------------------------------------------------------------------
# Python mirror: MIME type mapper
# ---------------------------------------------------------------------------


def mime_type(ext: str) -> str:
    """Python mirror of PS Get-MimeType."""
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        ext.lower(), "image/png"
    )


# ---------------------------------------------------------------------------
# Python mirror: resize logic
# ---------------------------------------------------------------------------


def compute_resize(width: int, height: int, max_dim: int = 1024) -> tuple[int, int]:
    """Return (new_w, new_h) preserving aspect ratio; unchanged if within max_dim."""
    if width <= max_dim and height <= max_dim:
        return width, height
    if width >= height:
        return max_dim, int(height / width * max_dim)
    return int(width / height * max_dim), max_dim


# ---------------------------------------------------------------------------
# Python mirror: markdown companion writer
# ---------------------------------------------------------------------------

_ENTITY_TYPE = {"portrait": "npc", "body": "creature", "battlemap": "location", "scene": "location"}


def write_companion_md(
    processing_dir: Path,
    image_name: str,
    type_: str,
    race: str = "none",
    class_: str = "none",
    element: str = "none",
    environment: str = "none",
    is_token: bool = False,
    description: str = "",
    sha256: str = "abc123",
) -> Path:
    """Python mirror of PS Write-ImageMarkdown."""
    base      = Path(image_name).stem
    entity    = _ENTITY_TYPE.get(type_, "npc")
    today     = date.today().isoformat()

    tags: list[str] = ["images", type_]
    if type_ in ("battlemap", "scene"):
        if environment != "none":
            tags.append(environment)
    else:
        tags += [v for v in (race, class_, element) if v != "none"]
        if is_token:
            tags.append("token")
    tags_yaml = "\n".join(f"  - {t}" for t in tags)

    fm = (
        f"---\n"
        f"id: {entity}-{base}\n"
        f"type: {entity}\n"
        f"status: draft\n"
        f"quality: 0\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"tags:\n{tags_yaml}\n"
        f"source:\n  - {image_name}\n"
        f"sha256: {sha256}\n"
        f"reviewed: false\n"
        f"relationships: []\n"
    )
    if type_ in ("battlemap", "scene"):
        fm += f"environment: {environment}\n"
    else:
        fm += f"race: {race}\nclass: {class_}\nelement: {element}\n"
        if is_token:
            fm += "token: true\n"
    fm += "---"

    embed = f"\n\n![[{image_name}]]"
    body  = (
        f"\n\n## Description\n\n{description}\n\n> sha256: `{sha256}`\n"
        if description
        else f"\n\n> sha256: `{sha256}`\n"
    )

    processing_dir.mkdir(parents=True, exist_ok=True)
    out = processing_dir / f"{base}.md"
    out.write_text(fm + embed + body, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def inbox(tmp_path: Path) -> Path:
    d = tmp_path / "00-Inbox" / "images" / "A1"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def processing(tmp_path: Path) -> Path:
    d = tmp_path / "01-Processing"
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------
# Tests: token detection
# ---------------------------------------------------------------------------


class TestTokenDetection:
    """Token detection mirrors PS Test-IsToken: transparent corners = token."""

    def test_token_png_detected(self, tmp_path: Path) -> None:
        path = _token_png(tmp_path / "t.png")
        assert detect_token(path) is True

    def test_solid_rgba_png_not_token(self, tmp_path: Path) -> None:
        img = Image.new("RGBA", (64, 64), (200, 100, 50, 255))
        path = tmp_path / "solid.png"
        img.save(path)
        assert detect_token(path) is False

    def test_rgb_png_no_alpha_not_token(self, tmp_path: Path) -> None:
        path = tmp_path / "rgb.png"
        _solid_rgb(path)
        assert detect_token(path) is False

    def test_jpeg_never_token(self, tmp_path: Path) -> None:
        path = tmp_path / "img.jpg"
        _solid_rgb(path)
        assert detect_token(path) is False

    def test_webp_never_token(self, tmp_path: Path) -> None:
        path = tmp_path / "img.webp"
        Image.new("RGB", (64, 64), (80, 160, 240)).save(path, "WEBP")
        assert detect_token(path) is False

    def test_fully_transparent_png_is_token(self, tmp_path: Path) -> None:
        path = tmp_path / "blank.png"
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(path)
        assert detect_token(path) is True

    def test_one_transparent_corner_not_token(self, tmp_path: Path) -> None:
        img = Image.new("RGBA", (64, 64), (200, 100, 50, 255))
        img.load()[0, 0] = (0, 0, 0, 0)  # only 1/8 transparent
        path = tmp_path / "one_corner.png"
        img.save(path)
        assert detect_token(path) is False

    def test_semi_transparent_corner_below_threshold_not_token(self, tmp_path: Path) -> None:
        img = Image.new("RGBA", (64, 64), (200, 100, 50, 255))
        px = img.load()
        # alpha = 200 (>= 128) at all corners - not transparent enough
        for x, y in [(0, 0), (63, 0), (0, 63), (63, 63)]:
            px[x, y] = (0, 0, 0, 200)
        path = tmp_path / "semi.png"
        img.save(path)
        assert detect_token(path) is False

    def test_exactly_two_transparent_points_is_token(self, tmp_path: Path) -> None:
        img = Image.new("RGBA", (64, 64), (200, 100, 50, 255))
        px = img.load()
        px[0, 0] = (0, 0, 0, 0)
        px[63, 0] = (0, 0, 0, 0)  # exactly 2 → threshold met
        path = tmp_path / "two_corners.png"
        img.save(path)
        assert detect_token(path) is True

    @pytest.mark.parametrize("ext", [".jpg", ".jpeg", ".webp"])
    def test_non_png_extension_not_token(self, tmp_path: Path, ext: str) -> None:
        path = tmp_path / f"img{ext}"
        path.write_bytes(b"\x00" * 16)
        assert detect_token(path) is False

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises((FileNotFoundError, OSError)):
            detect_token(tmp_path / "ghost.png")

    @pytest.mark.parametrize("size", [(8, 8), (16, 16), (128, 128), (512, 512)])
    def test_token_detection_various_sizes(self, tmp_path: Path, size: tuple[int, int]) -> None:
        path = _token_png(tmp_path / f"token_{size[0]}x{size[1]}.png", size=size)
        assert detect_token(path) is True


# ---------------------------------------------------------------------------
# Tests: slug / filename generation
# ---------------------------------------------------------------------------


class TestSlugGeneration:
    """Filename slug mirrors Resolve-TargetFilename logic."""

    @pytest.mark.parametrize("type_,race,cls,elem,env,is_tok,ext,expected", [
        ("portrait",  "human",    "warrior",     "fire",  "none",    False, ".jpg", "human-warrior-fire.portrait.jpg"),
        ("portrait",  "elf",      "mage",        "light", "none",    False, ".png", "elf-mage-light.portrait.png"),
        ("body",      "orc",      "warrior",     "fire",  "none",    False, ".png", "orc-warrior-fire.body.png"),
        ("body",      "dragon",   "monster",     "dark",  "none",    False, ".jpg", "dragon-monster-dark.body.jpg"),
        ("battlemap", "none",     "none",        "none",  "dungeon", False, ".jpg", "battlemap-dungeon.jpg"),
        ("battlemap", "human",    "warrior",     "fire",  "castle",  False, ".png", "battlemap-castle.png"),
        ("scene",     "none",     "none",        "none",  "forest",  False, ".webp","scene-forest.webp"),
        ("scene",     "elf",      "mage",        "light", "tavern",  False, ".jpg", "scene-tavern.jpg"),
        ("portrait",  "orc",      "warrior",     "none",  "none",    True,  ".png", "orc-warrior-none.token.png"),
        ("body",      "vampire",  "necromancer", "dark",  "none",    True,  ".png", "vampire-necromancer-dark.token.png"),
        ("portrait",  "dark-elf", "assassin",    "dark",  "none",    False, ".jpg", "dark-elf-assassin-dark.portrait.jpg"),
    ])
    def test_slug_format(
        self,
        type_: str, race: str, cls: str, elem: str, env: str,
        is_tok: bool, ext: str, expected: str,
    ) -> None:
        assert build_slug(type_, race, cls, elem, env, is_tok, ext) == expected

    def test_battlemap_ignores_character_fields(self) -> None:
        slug = build_slug("battlemap", race="human", class_="warrior", element="fire", environment="ruins")
        assert "human" not in slug and "warrior" not in slug and "fire" not in slug
        assert slug.startswith("battlemap-ruins")

    def test_scene_ignores_character_fields(self) -> None:
        slug = build_slug("scene", race="elf", class_="mage", element="light", environment="temple")
        assert "elf" not in slug and slug.startswith("scene-temple")

    def test_token_overrides_type_in_suffix(self) -> None:
        slug = build_slug("portrait", "human", "warrior", "none", is_token=True, ext=".png")
        assert ".token.png" in slug
        assert ".portrait" not in slug

    @pytest.mark.parametrize("env", sorted(_VALID_ENVIRONMENTS))
    def test_all_environments_produce_valid_battlemap_slug(self, env: str) -> None:
        slug = build_slug("battlemap", environment=env)
        assert slug == f"battlemap-{env}.jpg"

    @pytest.mark.parametrize("race", ["human", "elf", "dark-elf", "dwarf", "orc",
                                       "goblin", "troll", "ogre", "dragon", "vampire"])
    def test_race_present_in_character_slug(self, race: str) -> None:
        slug = build_slug("portrait", race=race, class_="warrior", element="none")
        assert race in slug

    @pytest.mark.parametrize("ext", [".jpg", ".jpeg", ".png", ".webp"])
    def test_extension_preserved(self, ext: str) -> None:
        slug = build_slug("portrait", ext=ext)
        assert slug.endswith(ext)


# ---------------------------------------------------------------------------
# Tests: LLM response normalisation
# ---------------------------------------------------------------------------


class TestLLMNormalisation:
    """Mirrors PS sanitisation inside Invoke-VisionLLM."""

    def test_valid_portrait_unchanged(self) -> None:
        raw = {"type": "portrait", "race": "human", "class": "warrior",
               "element": "fire", "environment": "none"}
        assert normalise_llm(raw) == raw

    @pytest.mark.parametrize("type_", sorted(_VALID_TYPES))
    def test_all_valid_types_accepted(self, type_: str) -> None:
        out = normalise_llm({"type": type_, "race": "none", "class": "none",
                              "element": "none", "environment": "dungeon"})
        assert out["type"] == type_

    def test_unknown_type_defaults_to_portrait(self) -> None:
        assert normalise_llm({"type": "character"})["type"] == "portrait"

    def test_empty_type_defaults_to_portrait(self) -> None:
        assert normalise_llm({})["type"] == "portrait"

    def test_battlemap_clears_character_fields(self) -> None:
        out = normalise_llm({"type": "battlemap", "race": "human",
                              "class": "warrior", "element": "fire", "environment": "dungeon"})
        assert out["race"] == "none"
        assert out["class"] == "none"
        assert out["element"] == "none"
        assert out["environment"] == "dungeon"

    def test_scene_clears_character_fields(self) -> None:
        out = normalise_llm({"type": "scene", "race": "elf",
                              "class": "mage", "element": "light", "environment": "forest"})
        assert out["race"] == out["class"] == out["element"] == "none"

    def test_invalid_race_becomes_unknown(self) -> None:
        assert normalise_llm({"type": "portrait", "race": "halfling",
                               "class": "none", "element": "none", "environment": "none"})["race"] == "unknown"

    def test_invalid_class_becomes_none(self) -> None:
        assert normalise_llm({"type": "portrait", "race": "human",
                               "class": "bard", "element": "none", "environment": "none"})["class"] == "none"

    def test_invalid_element_becomes_none(self) -> None:
        assert normalise_llm({"type": "portrait", "race": "human",
                               "class": "none", "element": "plasma", "environment": "none"})["element"] == "none"

    def test_invalid_environment_becomes_none(self) -> None:
        assert normalise_llm({"type": "battlemap", "race": "none",
                               "class": "none", "element": "none", "environment": "space"})["environment"] == "none"

    def test_explicit_none_race_preserved(self) -> None:
        assert normalise_llm({"type": "portrait", "race": "none",
                               "class": "warrior", "element": "none", "environment": "none"})["race"] == "none"

    @pytest.mark.parametrize("race", sorted(_VALID_RACES))
    def test_all_valid_races_accepted(self, race: str) -> None:
        out = normalise_llm({"type": "portrait", "race": race,
                              "class": "none", "element": "none", "environment": "none"})
        assert out["race"] == race

    @pytest.mark.parametrize("elem", sorted(_VALID_ELEMENTS - {"none"}))
    def test_all_valid_elements_accepted(self, elem: str) -> None:
        out = normalise_llm({"type": "portrait", "race": "human",
                              "class": "none", "element": elem, "environment": "none"})
        assert out["element"] == elem


# ---------------------------------------------------------------------------
# Tests: MIME type mapping
# ---------------------------------------------------------------------------


class TestMimeType:
    @pytest.mark.parametrize("ext,expected", [
        (".jpg",  "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".JPG",  "image/jpeg"),
        (".JPEG", "image/jpeg"),
        (".webp", "image/webp"),
        (".WEBP", "image/webp"),
        (".png",  "image/png"),
        (".PNG",  "image/png"),
        (".gif",  "image/png"),
        (".bmp",  "image/png"),
        (".tiff", "image/png"),
    ])
    def test_mime_mapping(self, ext: str, expected: str) -> None:
        assert mime_type(ext) == expected


# ---------------------------------------------------------------------------
# Tests: resize computation
# ---------------------------------------------------------------------------


class TestResizeComputation:
    def test_small_image_unchanged(self) -> None:
        assert compute_resize(512, 256, 1024) == (512, 256)

    def test_exact_boundary_unchanged(self) -> None:
        assert compute_resize(1024, 1024, 1024) == (1024, 1024)

    def test_wide_image_caps_width(self) -> None:
        nw, nh = compute_resize(2048, 1024, 1024)
        assert nw == 1024
        assert nh == 512

    def test_tall_image_caps_height(self) -> None:
        nw, nh = compute_resize(512, 2048, 1024)
        assert nh == 1024
        assert nw == 256

    def test_aspect_ratio_preserved_wide(self) -> None:
        nw, nh = compute_resize(3000, 2000, 1024)
        assert abs(nw / nh - 3000 / 2000) < 0.01

    def test_aspect_ratio_preserved_tall(self) -> None:
        nw, nh = compute_resize(1000, 4000, 1024)
        assert abs(nh / nw - 4000 / 1000) < 0.01

    @pytest.mark.parametrize("w,h,max_d,exp_w,exp_h", [
        (100,  100,  1024, 100,  100),
        (2000, 1000, 1024, 1024, 512),
        (500,  2000, 1024, 256,  1024),
        (1500, 1500, 500,  500,  500),
    ])
    def test_parametrised_resize(
        self, w: int, h: int, max_d: int, exp_w: int, exp_h: int
    ) -> None:
        assert compute_resize(w, h, max_d) == (exp_w, exp_h)


# ---------------------------------------------------------------------------
# Tests: companion markdown content
# ---------------------------------------------------------------------------


class TestCompanionMarkdown:
    def _md(self, processing: Path, **kwargs) -> str:
        path = write_companion_md(processing, **kwargs)
        return path.read_text(encoding="utf-8")

    def test_starts_with_yaml_fence(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait")
        assert md.startswith("---\n")

    @pytest.mark.parametrize("field", [
        "id:", "type:", "status:", "quality:", "created:", "updated:",
        "sha256:", "reviewed:", "relationships:",
    ])
    def test_required_fields_present(self, processing: Path, field: str) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait")
        assert field in md

    def test_status_draft(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait")
        assert "status: draft" in md

    def test_quality_zero(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait")
        assert "quality: 0" in md

    def test_reviewed_false(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait")
        assert "reviewed: false" in md

    @pytest.mark.parametrize("type_,entity", [
        ("portrait",  "npc"),
        ("body",      "creature"),
        ("battlemap", "location"),
        ("scene",     "location"),
    ])
    def test_entity_type_mapping(self, processing: Path, type_: str, entity: str) -> None:
        md = self._md(processing, image_name="test.jpg", type_=type_, environment="dungeon")
        assert f"type: {entity}" in md

    def test_portrait_has_race_class_element(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait",
                      race="human", class_="warrior", element="fire")
        assert "race: human" in md
        assert "class: warrior" in md
        assert "element: fire" in md

    def test_battlemap_has_environment_not_race(self, processing: Path) -> None:
        md = self._md(processing, image_name="map.jpg", type_="battlemap",
                      race="human", class_="warrior", environment="dungeon")
        assert "environment: dungeon" in md
        assert "race:" not in md

    def test_scene_has_environment_not_race(self, processing: Path) -> None:
        md = self._md(processing, image_name="scene.jpg", type_="scene",
                      race="elf", environment="forest")
        assert "environment: forest" in md
        assert "race:" not in md

    def test_token_true_in_frontmatter(self, processing: Path) -> None:
        md = self._md(processing, image_name="tok.png", type_="portrait",
                      race="orc", class_="warrior", is_token=True)
        assert "token: true" in md

    def test_token_tag_present(self, processing: Path) -> None:
        md = self._md(processing, image_name="tok.png", type_="portrait",
                      race="orc", class_="warrior", is_token=True)
        assert "  - token" in md

    def test_image_embed_wikilink(self, processing: Path) -> None:
        md = self._md(processing, image_name="elf-mage-light.portrait.jpg", type_="portrait")
        assert "![[elf-mage-light.portrait.jpg]]" in md

    def test_sha256_in_body(self, processing: Path) -> None:
        sha = "deadbeef" * 8
        md = self._md(processing, image_name="test.jpg", type_="portrait", sha256=sha)
        assert sha in md

    def test_description_section_written(self, processing: Path) -> None:
        desc = "A fierce orc warrior with a flaming axe."
        md = self._md(processing, image_name="test.jpg", type_="portrait", description=desc)
        assert "## Description" in md
        assert desc in md

    def test_no_description_omits_section(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait", description="")
        assert "## Description" not in md

    def test_utf8_encoded(self, processing: Path) -> None:
        desc = "Café du dragon - fée magique"
        md_path = write_companion_md(processing, image_name="test.jpg",
                                     type_="portrait", description=desc)
        raw = md_path.read_bytes()
        assert desc.encode("utf-8") in raw

    @pytest.mark.parametrize("type_", ["portrait", "body", "battlemap", "scene"])
    def test_tags_include_type(self, processing: Path, type_: str) -> None:
        md = self._md(processing, image_name="test.jpg", type_=type_, environment="dungeon")
        assert f"  - {type_}" in md

    def test_non_none_race_in_tags(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait",
                      race="vampire", class_="none", element="dark")
        assert "  - vampire" in md
        assert "  - dark" in md

    def test_none_values_omitted_from_tags(self, processing: Path) -> None:
        md = self._md(processing, image_name="test.jpg", type_="portrait",
                      race="none", class_="none", element="none")
        lines = [ln.strip() for ln in md.splitlines() if ln.strip().startswith("- none")]
        assert lines == [], f"'none' should not appear as tag, found: {lines}"


# ---------------------------------------------------------------------------
# Tests: JSON index structure
# ---------------------------------------------------------------------------


class TestJsonIndexStructure:
    def test_v2_round_trip(self, tmp_path: Path) -> None:
        entry = {
            "sha256": "abc" * 21 + "a",
            "path": "00-Inbox\\images\\A1\\test.jpg",
            "type": "portrait", "race": "human", "class": "warrior",
            "element": "none", "environment": "none", "status": "ok",
        }
        idx = {"version": 2, "images": {entry["sha256"]: entry},
               "pathIndex": {entry["path"]: entry["sha256"]}}
        p = tmp_path / "index.json"
        p.write_text(json.dumps(idx, indent=2), encoding="utf-8")

        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded["version"] == 2
        assert entry["sha256"] in loaded["images"]
        assert loaded["pathIndex"][entry["path"]] == entry["sha256"]

    def test_sha256_key_not_path_key(self, tmp_path: Path) -> None:
        sha = "a" * 64
        idx = {"version": 2, "images": {sha: {"sha256": sha, "path": "x.jpg", "status": "ok"}},
               "pathIndex": {"x.jpg": sha}}
        p = tmp_path / "index.json"
        p.write_text(json.dumps(idx), encoding="utf-8")
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert sha in loaded["images"]
        assert "x.jpg" not in loaded["images"]

    def test_failed_entry_uses_path_prefix(self) -> None:
        rel = "00-Inbox\\images\\A1\\bad.jpg"
        pseudo = f"path:{rel}"
        idx: dict = {"version": 2, "images": {}, "pathIndex": {}}
        idx["images"][pseudo] = {"path": rel, "status": "failed"}
        idx["pathIndex"][rel] = pseudo
        assert idx["pathIndex"][rel].startswith("path:")
        assert idx["images"][pseudo]["status"] == "failed"

    def test_duplicate_sha256_overwrite(self) -> None:
        sha = "b" * 64
        idx: dict = {"version": 2, "images": {sha: {"path": "old.jpg", "status": "ok"}}, "pathIndex": {}}
        idx["images"][sha]["path"] = "new.jpg"
        assert idx["images"][sha]["path"] == "new.jpg"
        assert len(idx["images"]) == 1

    def test_empty_index_valid_structure(self) -> None:
        idx = {"version": 2, "images": {}, "pathIndex": {}}
        assert idx["version"] == 2
        assert not idx["images"]
        assert not idx["pathIndex"]


# ---------------------------------------------------------------------------
# Tests: image comparison helpers (Pillow + SSIM)
# ---------------------------------------------------------------------------


class TestImageComparisonHelpers:
    def test_identical_images_equal(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (32, 32), (100, 150, 200))
        p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
        img.save(p1)
        img.save(p2)
        assert images_are_equal(p1, p2) is True

    def test_different_colour_not_equal(self, tmp_path: Path) -> None:
        p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
        Image.new("RGB", (32, 32), (100, 150, 200)).save(p1)
        Image.new("RGB", (32, 32), (200, 50, 100)).save(p2)
        assert images_are_equal(p1, p2) is False

    def test_different_size_not_equal(self, tmp_path: Path) -> None:
        p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
        Image.new("RGB", (32, 32), (100, 100, 100)).save(p1)
        Image.new("RGB", (64, 64), (100, 100, 100)).save(p2)
        assert images_are_equal(p1, p2) is False

    def test_rgb_vs_rgba_identical_content_equal(self, tmp_path: Path) -> None:
        p1, p2 = tmp_path / "rgb.png", tmp_path / "rgba.png"
        Image.new("RGB",  (16, 16), (80, 80, 80)).save(p1)
        Image.new("RGBA", (16, 16), (80, 80, 80, 255)).save(p2)
        assert images_are_equal(p1, p2) is True

    @pytest.mark.skipif(not HAS_SKIMAGE, reason="scikit-image not available")
    def test_ssim_identical_passes(self, tmp_path: Path) -> None:
        img = Image.new("RGB", (64, 64), (128, 64, 32))
        p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
        img.save(p1)
        img.save(p2)
        assert_images_similar(p1, p2, min_ssim=0.99)

    @pytest.mark.skipif(not HAS_SKIMAGE, reason="scikit-image not available")
    def test_ssim_near_identical_passes(self, tmp_path: Path) -> None:
        """Near-duplicate image (JPEG re-encoding) meets 0.90 SSIM."""
        src = Image.new("RGB", (128, 128), (100, 100, 100))
        p1 = tmp_path / "orig.png"
        p2 = tmp_path / "reenc.jpg"
        src.save(p1, "PNG")
        src.save(p2, "JPEG", quality=85)
        assert_images_similar(p1, p2, min_ssim=0.90)

    @pytest.mark.skipif(not HAS_SKIMAGE, reason="scikit-image not available")
    def test_ssim_black_vs_white_fails(self, tmp_path: Path) -> None:
        p1, p2 = tmp_path / "black.png", tmp_path / "white.png"
        Image.new("RGB", (64, 64), (0, 0, 0)).save(p1)
        Image.new("RGB", (64, 64), (255, 255, 255)).save(p2)
        with pytest.raises(AssertionError, match="SSIM"):
            assert_images_similar(p1, p2, min_ssim=0.95)

    @pytest.mark.skipif(not HAS_SKIMAGE, reason="scikit-image not available")
    def test_ssim_different_sizes_resized(self, tmp_path: Path) -> None:
        """assert_images_similar resizes before comparison - no crash."""
        img = Image.new("RGB", (64, 64), (100, 150, 200))
        p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
        img.save(p1)
        img.resize((32, 32)).save(p2)
        assert_images_similar(p1, p2, min_ssim=0.90)
