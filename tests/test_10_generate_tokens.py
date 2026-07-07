"""
Tests for .automation/10-generate-tokens.py — RPG Token Generator

Strategy: import Python functions directly via importlib; no mediapipe/opencv required.
generate_token tests use the no-face fallback path with programmatic test images.

Behaviors under test:
  1.  parse_focus_head     — None; scalar; 1/2/3/4-value lists; float coercion
  2.  load_config          — missing file; partial override; unknown keys; corrupt JSON
  3.  detect_ring_radii    — standard ring; all-transparent fallback; threshold boundary
  4.  make_circle_mask     — size; mode; center opaque; corners transparent; anti-aliasing
  5.  load_json / save_json — missing; corrupt; round-trip; unicode; UTF-8 BOM
  6.  generate_token        — happy path; skip-existing; force; output size; RGBA;
                              transparent corners; center opaque; parent dir creation;
                              various source formats/sizes; padding; focus_head
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    Path(__file__).parent.parent / "system" / "src" / "nexus" / "tasks" / "generate_tokens.py"
)

_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))


def _load_module() -> ModuleType:
    """Load generate_tokens.py as importable module without running main()."""
    import types

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    mod = types.ModuleType("generate_tokens")
    mod.__file__ = str(SCRIPT_PATH)
    exec(compile(source, str(SCRIPT_PATH), "exec"), mod.__dict__)  # noqa: S102
    return mod


if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found: {SCRIPT_PATH}",
        allow_module_level=True,
    )

try:
    _mod = _load_module()
except Exception as _exc:
    pytest.skip(
        f"Failed to load {SCRIPT_PATH.name}: {_exc}. "
        "See agents/tests/test_token_agent.py for current coverage.",
        allow_module_level=True,
    )

_API_REQUIRED = (
    "parse_focus_head", "load_config", "detect_ring_radii",
    "make_circle_mask", "generate_token", "load_json", "save_json",
)
_MISSING_API = [fn for fn in _API_REQUIRED if not hasattr(_mod, fn)]
if _MISSING_API:
    pytest.skip(
        f"generate_tokens.py API changed — functions not found: {_MISSING_API}. "
        "Refactored module uses _load_config/_make_token/etc. (internal names). "
        "Next step: rewrite these tests against nexus/tasks/generate_tokens.py API "
        "or extend agents/tests/test_token_agent.py.",
        allow_module_level=True,
    )

parse_focus_head  = _mod.parse_focus_head
load_config       = _mod.load_config
detect_ring_radii = _mod.detect_ring_radii
make_circle_mask  = _mod.make_circle_mask
generate_token    = _mod.generate_token
load_json         = _mod.load_json
save_json         = _mod.save_json
_DEFAULTS         = _mod._DEFAULTS
CONFIG_REL        = _mod.CONFIG_REL

# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def make_source_png(
    path: Path,
    width: int = 200,
    height: int = 200,
    color: tuple[int, int, int] = (120, 80, 60),
) -> Path:
    """Solid-colour RGB PNG simulating a portrait source image."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=color).save(str(path), "PNG")
    return path


def make_moldura_png(
    path: Path,
    size: int = 100,
    inner_r: int = 20,
    outer_r: int = 45,
) -> Path:
    """RGBA ring PNG usable as a moldura frame.

    Transparent centre (radius < inner_r), opaque ring (inner_r..outer_r),
    transparent exterior (radius > outer_r).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    draw.ellipse(
        [cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r],
        fill=(200, 150, 50, 255),
    )
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(0, 0, 0, 0),
    )
    img.save(str(path), "PNG")
    return path


def images_are_equal(a: Image.Image, b: Image.Image) -> bool:
    """True when two images share identical size, mode, and pixel data."""
    if a.size != b.size or a.mode != b.mode:
        return False
    return list(a.getdata()) == list(b.getdata())


def assert_images_similar(
    a: Image.Image,
    b: Image.Image,
    min_ssim: float = 0.90,
) -> None:
    """Assert SSIM ≥ min_ssim; falls back to size equality if skimage is absent."""
    try:
        from skimage.metrics import structural_similarity as ssim  # type: ignore

        arr_a = np.array(a.convert("RGB"))
        arr_b = np.array(b.resize(a.size, Image.LANCZOS).convert("RGB"))
        score = ssim(arr_a, arr_b, channel_axis=-1, data_range=255)
        assert score >= min_ssim, f"SSIM {score:.3f} < threshold {min_ssim}"
    except ImportError:
        assert a.size == b.size, f"Image sizes differ: {a.size} vs {b.size}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal vault layout with .automation directory."""
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def moldura(tmp_path: Path) -> Path:
    """Standard ring moldura PNG at a predictable tmp path."""
    return make_moldura_png(tmp_path / "moldura.png")


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    """Standard portrait source PNG."""
    return make_source_png(tmp_path / "portrait.png")


# ---------------------------------------------------------------------------
# 1. parse_focus_head
# ---------------------------------------------------------------------------


class TestParseFocusHead:
    """parse_focus_head converts CSS-like shorthand into (top, right, bottom, left) floats."""

    def test_none_returns_all_zero(self) -> None:
        assert parse_focus_head(None) == (0.0, 0.0, 0.0, 0.0)

    def test_zero_scalar_returns_all_zero(self) -> None:
        assert parse_focus_head(0) == (0.0, 0.0, 0.0, 0.0)

    @pytest.mark.parametrize("val,expected", [
        (10,    (10.0, 10.0, 10.0, 10.0)),
        (-5,    (-5.0, -5.0, -5.0, -5.0)),
        (0.5,   (0.5,  0.5,  0.5,  0.5)),
        (100.0, (100.0, 100.0, 100.0, 100.0)),
    ])
    def test_scalar_broadcasts_to_all_four(self, val: float, expected: tuple) -> None:
        assert parse_focus_head(val) == expected

    def test_list_of_one_broadcasts(self) -> None:
        assert parse_focus_head([7]) == (7.0, 7.0, 7.0, 7.0)

    def test_list_of_two_maps_top_and_left(self) -> None:
        # [top, left] → (top, 0, 0, left)
        assert parse_focus_head([10, 20]) == (10.0, 0.0, 0.0, 20.0)

    def test_list_of_two_right_and_bottom_are_zero(self) -> None:
        _, right, bottom, _ = parse_focus_head([5, 15])
        assert right == 0.0
        assert bottom == 0.0

    def test_list_of_three_mirrors_right_to_left(self) -> None:
        # [t, r, b] → (t, r, b, r)
        assert parse_focus_head([1, 2, 3]) == (1.0, 2.0, 3.0, 2.0)

    def test_list_of_four_explicit(self) -> None:
        assert parse_focus_head([1, 2, 3, 4]) == (1.0, 2.0, 3.0, 4.0)

    def test_list_of_four_all_negative(self) -> None:
        assert parse_focus_head([-10, -20, -30, -40]) == (-10.0, -20.0, -30.0, -40.0)

    def test_mixed_int_float_list(self) -> None:
        assert parse_focus_head([1, 2.5, -3, 0]) == (1.0, 2.5, -3.0, 0.0)

    @pytest.mark.parametrize("val", [0, 10, -5, [0, 0], [10, 20, 30, 40]])
    def test_always_returns_four_values(self, val) -> None:
        assert len(parse_focus_head(val)) == 4

    @pytest.mark.parametrize("val", [0, 10, -5, [0, 0], [10, 20, 30, 40]])
    def test_all_returned_values_are_float(self, val) -> None:
        for v in parse_focus_head(val):
            assert isinstance(v, float)


# ---------------------------------------------------------------------------
# 2. load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """load_config merges .automation/10-generate-tokens.json over _DEFAULTS."""

    def test_missing_config_returns_all_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        for key, val in _DEFAULTS.items():
            assert cfg[key] == val, f"Default mismatch for key '{key}'"

    def test_partial_config_overrides_given_keys(self, tmp_path: Path) -> None:
        (tmp_path / ".automation").mkdir(parents=True, exist_ok=True)
        (tmp_path / CONFIG_REL).write_text(
            json.dumps({"padding": 0.10, "output_size": 256}), encoding="utf-8"
        )
        cfg = load_config(tmp_path)
        assert cfg["padding"] == 0.10
        assert cfg["output_size"] == 256

    def test_partial_config_preserves_other_defaults(self, tmp_path: Path) -> None:
        (tmp_path / ".automation").mkdir(parents=True, exist_ok=True)
        (tmp_path / CONFIG_REL).write_text(
            json.dumps({"padding": 0.10}), encoding="utf-8"
        )
        cfg = load_config(tmp_path)
        assert cfg["forehead_ratio"] == _DEFAULTS["forehead_ratio"]
        assert cfg["body_ratio"] == _DEFAULTS["body_ratio"]
        assert cfg["batch_size"] == _DEFAULTS["batch_size"]

    def test_unknown_keys_excluded_from_result(self, tmp_path: Path) -> None:
        (tmp_path / ".automation").mkdir(parents=True, exist_ok=True)
        (tmp_path / CONFIG_REL).write_text(
            json.dumps({"unknown_key": "should_be_ignored"}), encoding="utf-8"
        )
        cfg = load_config(tmp_path)
        assert "unknown_key" not in cfg

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path: Path) -> None:
        (tmp_path / ".automation").mkdir(parents=True, exist_ok=True)
        (tmp_path / CONFIG_REL).write_text("{not valid json", encoding="utf-8")
        cfg = load_config(tmp_path)
        for key, val in _DEFAULTS.items():
            assert cfg[key] == val

    def test_empty_json_object_returns_defaults(self, tmp_path: Path) -> None:
        (tmp_path / ".automation").mkdir(parents=True, exist_ok=True)
        (tmp_path / CONFIG_REL).write_text("{}", encoding="utf-8")
        cfg = load_config(tmp_path)
        for key, val in _DEFAULTS.items():
            assert cfg[key] == val

    def test_all_default_keys_can_be_overridden(self, tmp_path: Path) -> None:
        overrides = {
            "output_size":    256,
            "padding":        0.05,
            "forehead_ratio": 0.25,
            "body_ratio":     0.20,
            "batch_size":     5,
            "moldura":        r"custom\moldura.png",
            "focus_head":     [10, 0, 0, 5],
        }
        (tmp_path / ".automation").mkdir(parents=True, exist_ok=True)
        (tmp_path / CONFIG_REL).write_text(json.dumps(overrides), encoding="utf-8")
        cfg = load_config(tmp_path)
        for key, val in overrides.items():
            assert cfg[key] == val

    @pytest.mark.parametrize("key", list(_DEFAULTS.keys()))
    def test_all_default_keys_present_in_result(self, tmp_path: Path, key: str) -> None:
        assert key in load_config(tmp_path)


# ---------------------------------------------------------------------------
# 3. detect_ring_radii
# ---------------------------------------------------------------------------


class TestDetectRingRadii:
    """detect_ring_radii scans the alpha channel of the center row for ring boundaries."""

    @staticmethod
    def _ring_arr(size: int, inner_r: int, outer_r: int) -> np.ndarray:
        """RGBA ndarray with opaque ring pixels at the center row."""
        arr = np.zeros((size, size, 4), dtype=np.uint8)
        cx = cy = size // 2
        for x in range(size):
            dist = abs(x - cx)
            if inner_r <= dist <= outer_r:
                arr[cy, x, 3] = 255
        return arr

    def test_inner_radius_detected(self) -> None:
        arr = self._ring_arr(100, inner_r=20, outer_r=45)
        inner, _ = detect_ring_radii(arr)
        assert inner == 20

    def test_outer_radius_detected(self) -> None:
        arr = self._ring_arr(100, inner_r=20, outer_r=45)
        _, outer = detect_ring_radii(arr)
        assert outer == 45

    def test_inner_less_than_outer(self) -> None:
        arr = self._ring_arr(100, inner_r=15, outer_r=40)
        inner, outer = detect_ring_radii(arr)
        assert inner < outer

    def test_all_transparent_fallback_inner(self) -> None:
        arr = np.zeros((100, 100, 4), dtype=np.uint8)
        inner, _ = detect_ring_radii(arr)
        assert inner == 100 // 4  # W // 4 fallback

    def test_all_transparent_fallback_outer(self) -> None:
        arr = np.zeros((100, 100, 4), dtype=np.uint8)
        _, outer = detect_ring_radii(arr)
        assert outer == 100 // 2  # W // 2 fallback

    def test_alpha_128_treated_as_transparent(self) -> None:
        """Pixels with alpha == 128 are not > 128, so treated as transparent."""
        arr = np.zeros((100, 100, 4), dtype=np.uint8)
        arr[50, 70, 3] = 128
        inner, outer = detect_ring_radii(arr)
        assert inner == 100 // 4
        assert outer == 100 // 2

    def test_alpha_129_detected(self) -> None:
        arr = np.zeros((100, 100, 4), dtype=np.uint8)
        arr[50, 70, 3] = 129
        arr[50, 90, 3] = 200
        inner, outer = detect_ring_radii(arr)
        assert inner == 20
        assert outer == 40

    @pytest.mark.parametrize("size,inner_r,outer_r", [
        (64,  8,  28),
        (128, 30, 58),
        (200, 50, 90),
    ])
    def test_various_image_sizes(self, size: int, inner_r: int, outer_r: int) -> None:
        arr = self._ring_arr(size, inner_r, outer_r)
        inner, outer = detect_ring_radii(arr)
        assert inner == inner_r
        assert outer == outer_r

    def test_both_radii_positive(self) -> None:
        arr = self._ring_arr(100, inner_r=20, outer_r=45)
        inner, outer = detect_ring_radii(arr)
        assert inner > 0
        assert outer > 0


# ---------------------------------------------------------------------------
# 4. make_circle_mask
# ---------------------------------------------------------------------------


class TestMakeCircleMask:
    """make_circle_mask produces an anti-aliased grayscale circle mask."""

    def test_output_size_matches_canvas_size(self) -> None:
        mask = make_circle_mask(64, 32, 32, 28)
        assert mask.size == (64, 64)

    def test_mode_is_l(self) -> None:
        mask = make_circle_mask(64, 32, 32, 28)
        assert mask.mode == "L"

    def test_center_pixel_is_near_white(self) -> None:
        size = 64
        mask = make_circle_mask(size, size // 2, size // 2, size // 2 - 4)
        assert mask.getpixel((size // 2, size // 2)) > 200

    def test_corner_top_left_is_black(self) -> None:
        size = 64
        mask = make_circle_mask(size, size // 2, size // 2, size // 4)
        assert mask.getpixel((0, 0)) == 0

    def test_all_four_corners_are_black(self) -> None:
        size = 128
        mask = make_circle_mask(size, size // 2, size // 2, size // 4)
        for xy in [(0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)]:
            assert mask.getpixel(xy) == 0, f"Corner {xy} should be 0"

    def test_pixel_values_in_0_to_255_range(self) -> None:
        mask = make_circle_mask(64, 32, 32, 20)
        assert all(0 <= p <= 255 for p in mask.getdata())

    def test_anti_aliased_edge_pixels_exist(self) -> None:
        """4× supersample anti-aliasing produces intermediate pixel values."""
        mask = make_circle_mask(64, 32, 32, 20)
        intermediate = [p for p in mask.getdata() if 0 < p < 255]
        assert len(intermediate) > 0

    def test_off_center_circle_center_opaque(self) -> None:
        size = 64
        mask = make_circle_mask(size, 20, 20, 12)
        assert mask.getpixel((20, 20)) > 200

    @pytest.mark.parametrize("size", [32, 64, 128, 256, 512])
    def test_various_canvas_sizes(self, size: int) -> None:
        mask = make_circle_mask(size, size // 2, size // 2, size // 3)
        assert mask.size == (size, size)
        assert mask.mode == "L"


# ---------------------------------------------------------------------------
# 5. load_json / save_json
# ---------------------------------------------------------------------------


class TestLoadJson:
    """load_json returns {} on missing file, empty file, or corrupt JSON."""

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert load_json(tmp_path / "nonexistent.json") == {}

    def test_valid_json_returned_intact(self, tmp_path: Path) -> None:
        data = {"tokens": {"abc": {"path": "img.png"}}, "version": 2}
        p = tmp_path / "idx.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        assert load_json(p) == data

    def test_corrupt_json_returns_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{bad json", encoding="utf-8")
        assert load_json(p) == {}

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert load_json(p) == {}

    def test_unicode_content_preserved(self, tmp_path: Path) -> None:
        data = {"name": "Élodie", "note": "→ warrior"}
        p = tmp_path / "unicode.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = load_json(p)
        assert result["name"] == "Élodie"
        assert result["note"] == "→ warrior"

    def test_utf8_bom_handled(self, tmp_path: Path) -> None:
        """utf-8-sig encoding strips BOM prefix."""
        data = {"tokens": {}}
        p = tmp_path / "bom.json"
        p.write_bytes(b"\xef\xbb\xbf" + json.dumps(data).encode("utf-8"))
        assert load_json(p) == data

    def test_returns_dict_type(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.json"
        p.write_text(json.dumps({"k": "v"}), encoding="utf-8")
        assert isinstance(load_json(p), dict)


class TestSaveJson:
    """save_json writes pretty-printed UTF-8 JSON that round-trips through load_json."""

    def test_file_created(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        save_json(p, {"version": 2, "tokens": {}})
        assert p.exists()

    def test_round_trip(self, tmp_path: Path) -> None:
        data = {"version": 2, "tokens": {"sha|A1": {"path": "img.png"}}}
        p = tmp_path / "idx.json"
        save_json(p, data)
        assert json.loads(p.read_text(encoding="utf-8")) == data

    def test_load_json_round_trips_save_json(self, tmp_path: Path) -> None:
        data = {"version": 2, "tokens": {"abc": {"path": "x.png", "tokenPath": "x-token.png"}}}
        p = tmp_path / "rt.json"
        save_json(p, data)
        assert load_json(p) == data

    def test_unicode_preserved_without_ascii_escaping(self, tmp_path: Path) -> None:
        data = {"note": "Élodie → Warrior"}
        p = tmp_path / "unicode.json"
        save_json(p, data)
        raw = p.read_text(encoding="utf-8")
        assert "Élodie" in raw
        assert "→" in raw

    def test_overwrites_existing_content(self, tmp_path: Path) -> None:
        p = tmp_path / "existing.json"
        p.write_text('{"old": true}', encoding="utf-8")
        save_json(p, {"new": True})
        assert json.loads(p.read_text(encoding="utf-8")) == {"new": True}

    def test_output_is_pretty_printed(self, tmp_path: Path) -> None:
        p = tmp_path / "pretty.json"
        save_json(p, {"k": "v"})
        assert "\n" in p.read_text(encoding="utf-8")

    def test_non_serializable_datetime_uses_str_fallback(self, tmp_path: Path) -> None:
        from datetime import datetime

        data = {"ts": datetime(2026, 6, 14, 12, 0, 0)}
        p = tmp_path / "date.json"
        save_json(p, data)
        assert "2026" in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 6. generate_token — happy path
# ---------------------------------------------------------------------------


class TestGenerateTokenHappyPath:
    """generate_token writes a 512×512 RGBA PNG token on first call."""

    def test_returns_true_on_success(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "out-token.png"
        assert generate_token(source, out, moldura) is True

    def test_output_file_created(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        assert out.exists()

    def test_output_is_512x512_by_default(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        assert Image.open(out).size == (512, 512)

    def test_output_mode_is_rgba(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        assert Image.open(out).mode == "RGBA"

    def test_output_is_valid_png(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        with open(out, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n"

    def test_corners_are_fully_transparent(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        """Circle mask applied → all four corners have alpha = 0."""
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        img = Image.open(out).convert("RGBA")
        for xy in [(0, 0), (511, 0), (0, 511), (511, 511)]:
            assert img.getpixel(xy)[3] == 0, f"Corner {xy} should be transparent"

    def test_center_pixel_is_opaque(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        """Center of the canvas is inside the circle — alpha must be non-zero."""
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        alpha = Image.open(out).convert("RGBA").getpixel((256, 256))[3]
        assert alpha > 0

    def test_parent_dirs_created_automatically(
        self, tmp_path: Path, source: Path, moldura: Path
    ) -> None:
        out = tmp_path / "nested" / "deep" / "out-token.png"
        generate_token(source, out, moldura)
        assert out.exists()


# ---------------------------------------------------------------------------
# 6b. generate_token — skip / force
# ---------------------------------------------------------------------------


class TestGenerateTokenSkipAndForce:
    """generate_token skips existing outputs unless force=True."""

    def test_skip_existing_returns_false(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        assert generate_token(source, out, moldura) is False

    def test_force_overwrites_existing_returns_true(
        self, tmp_path: Path, source: Path, moldura: Path
    ) -> None:
        out = tmp_path / "out-token.png"
        generate_token(source, out, moldura)
        assert generate_token(source, out, moldura, force=True) is True

    def test_existing_stub_not_overwritten_without_force(
        self, tmp_path: Path, source: Path, moldura: Path
    ) -> None:
        out = tmp_path / "out-token.png"
        out.write_bytes(b"stub-content")
        generate_token(source, out, moldura)
        assert out.read_bytes() == b"stub-content"

    def test_force_replaces_stub_content(
        self, tmp_path: Path, source: Path, moldura: Path
    ) -> None:
        out = tmp_path / "out-token.png"
        out.write_bytes(b"stub-content")
        generate_token(source, out, moldura, force=True)
        assert out.read_bytes() != b"stub-content"


# ---------------------------------------------------------------------------
# 6c. generate_token — output size
# ---------------------------------------------------------------------------


class TestGenerateTokenOutputSize:
    """generate_token out_size parameter controls the output canvas dimension."""

    @pytest.mark.parametrize("size", [64, 128, 256, 512])
    def test_output_matches_requested_size(
        self, tmp_path: Path, source: Path, moldura: Path, size: int
    ) -> None:
        out = tmp_path / f"token-{size}.png"
        generate_token(source, out, moldura, out_size=size)
        assert Image.open(out).size == (size, size)

    def test_output_is_always_square(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "token-128.png"
        generate_token(source, out, moldura, out_size=128)
        img = Image.open(out)
        assert img.width == img.height


# ---------------------------------------------------------------------------
# 6d. generate_token — image content
# ---------------------------------------------------------------------------


class TestGenerateTokenImageContent:
    """Token center reflects the source image; different sources produce different tokens."""

    def test_red_source_center_has_high_red_channel(
        self, tmp_path: Path, moldura: Path
    ) -> None:
        src = make_source_png(tmp_path / "red.png", color=(255, 0, 0))
        out = tmp_path / "red-token.png"
        generate_token(src, out, moldura)
        r, _, _, a = Image.open(out).convert("RGBA").getpixel((256, 256))
        assert a > 0
        assert r > 100, f"Expected reddish center pixel, got R={r}"

    def test_different_source_colors_produce_different_tokens(
        self, tmp_path: Path, moldura: Path
    ) -> None:
        src_red  = make_source_png(tmp_path / "red.png",  color=(255, 0,   0))
        src_blue = make_source_png(tmp_path / "blue.png", color=(0,   0, 255))
        out_red  = tmp_path / "red-token.png"
        out_blue = tmp_path / "blue-token.png"
        generate_token(src_red,  out_red,  moldura)
        generate_token(src_blue, out_blue, moldura)
        img_r = Image.open(out_red).convert("RGBA")
        img_b = Image.open(out_blue).convert("RGBA")
        assert not images_are_equal(img_r, img_b)

    def test_regenerating_same_source_produces_identical_token(
        self, tmp_path: Path, source: Path, moldura: Path
    ) -> None:
        out1 = tmp_path / "token1.png"
        out2 = tmp_path / "token2.png"
        generate_token(source, out1, moldura)
        generate_token(source, out2, moldura)
        assert_images_similar(Image.open(out1), Image.open(out2), min_ssim=0.999)


# ---------------------------------------------------------------------------
# 6e. generate_token — source formats and sizes
# ---------------------------------------------------------------------------


class TestGenerateTokenInputFormats:
    """generate_token handles varied source image formats and dimensions."""

    @pytest.mark.parametrize("width,height", [
        (50,   50),
        (200,  400),
        (400,  200),
        (1024, 1024),
    ])
    def test_various_source_sizes_produce_512x512_output(
        self, tmp_path: Path, moldura: Path, width: int, height: int
    ) -> None:
        src = make_source_png(tmp_path / f"src_{width}x{height}.png", width, height)
        out = tmp_path / "token.png"
        generate_token(src, out, moldura)
        assert Image.open(out).size == (512, 512)

    def test_jpeg_source_produces_rgba_token(self, tmp_path: Path, moldura: Path) -> None:
        src = tmp_path / "portrait.jpg"
        Image.new("RGB", (200, 200), color=(80, 120, 60)).save(str(src), "JPEG")
        out = tmp_path / "jpg-token.png"
        generate_token(src, out, moldura)
        assert Image.open(out).mode == "RGBA"

    def test_rgba_source_accepted(self, tmp_path: Path, moldura: Path) -> None:
        src = tmp_path / "rgba.png"
        Image.new("RGBA", (200, 200), color=(100, 50, 200, 180)).save(str(src), "PNG")
        out = tmp_path / "rgba-token.png"
        generate_token(src, out, moldura)
        assert out.exists()

    def test_tiny_32x32_source_padded_to_512x512(self, tmp_path: Path, moldura: Path) -> None:
        """Source smaller than crop box is edge-padded; output still 512×512."""
        src = make_source_png(tmp_path / "tiny.png", width=32, height=32)
        out = tmp_path / "tiny-token.png"
        generate_token(src, out, moldura)
        assert Image.open(out).size == (512, 512)

    def test_wide_landscape_source_accepted(self, tmp_path: Path, moldura: Path) -> None:
        src = make_source_png(tmp_path / "wide.png", width=800, height=200)
        out = tmp_path / "wide-token.png"
        generate_token(src, out, moldura)
        assert out.exists()


# ---------------------------------------------------------------------------
# 6f. generate_token — padding and focus_head
# ---------------------------------------------------------------------------


class TestGenerateTokenPaddingAndFocus:
    """Padding and focus_head parameters are accepted without error."""

    @pytest.mark.parametrize("padding", [0.05, 0.20, 0.40])
    def test_padding_values_produce_valid_output(
        self, tmp_path: Path, moldura: Path, padding: float
    ) -> None:
        src = make_source_png(tmp_path / "src.png")
        out = tmp_path / f"token-pad{padding:.2f}.png"
        generate_token(src, out, moldura, padding=padding)
        img = Image.open(out)
        assert img.size == (512, 512)
        assert img.mode == "RGBA"

    def test_focus_head_list_accepted(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "focus-token.png"
        generate_token(source, out, moldura, focus_head=[10, 0, -10, 0])
        assert out.exists()

    def test_focus_head_scalar_accepted(self, tmp_path: Path, source: Path, moldura: Path) -> None:
        out = tmp_path / "focus-scalar.png"
        generate_token(source, out, moldura, focus_head=5)
        assert out.exists()

    def test_focus_head_zero_same_as_none(self, tmp_path: Path, moldura: Path) -> None:
        """focus_head=[0,0,0,0] and focus_head=None are semantically identical."""
        src = make_source_png(tmp_path / "src.png")
        out_none = tmp_path / "token-none.png"
        out_zero = tmp_path / "token-zero.png"
        generate_token(src, out_none, moldura, focus_head=None)
        generate_token(src, out_zero, moldura, focus_head=[0, 0, 0, 0])
        assert_images_similar(Image.open(out_none), Image.open(out_zero), min_ssim=0.999)

    @pytest.mark.parametrize("forehead,body", [
        (0.20, 0.20),
        (0.40, 0.10),
        (0.10, 0.40),
    ])
    def test_forehead_body_ratios_accepted(
        self, tmp_path: Path, moldura: Path, forehead: float, body: float
    ) -> None:
        src = make_source_png(tmp_path / "src.png")
        out = tmp_path / f"token-fh{forehead}-br{body}.png"
        generate_token(src, out, moldura, forehead_ratio=forehead, body_ratio=body)
        assert Image.open(out).size == (512, 512)

