"""
Tests for .automation/06-match-token.py

Strategy:
- Load module via importlib.util (handles the numeric filename prefix)
- Unit test each internal function with mocked external libraries
  (face_recognition, imagehash) - no real models or GPU required
- CLI integration tests via subprocess - validate JSON stdout contract
- All temp files via tmp_path; no global state mutations

Behaviors under test:
  1.  _crop_circle_content  - bounding-box crop, mode conversion, edge cases
  2.  _match_imagehash      - hash comparison, threshold, multi-candidate, errors
  3.  _match_face_recognition - encoding compare, threshold, multi-candidate, errors
  4.  main() CLI            - JSON output contract, missing files, method flags
  5.  Auto method selection - library fallback chain
  6.  Parametrized          - sizes, thresholds, boundary conditions
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

# Library availability flags - used to skip CLI tests that need real installs
_IMAGEHASH_AVAILABLE = importlib.util.find_spec("imagehash") is not None
_FACE_REC_AVAILABLE = importlib.util.find_spec("face_recognition") is not None

_skip_no_imagehash = pytest.mark.skipif(
    not _IMAGEHASH_AVAILABLE, reason="imagehash not installed"
)

# ---------------------------------------------------------------------------
# Module loader - importlib handles the "06-" numeric prefix
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "06-match-token.py"


def _load_module():
    """Load 06-match-token.py as a Python module object."""
    spec = importlib.util.spec_from_file_location("match_token", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if not SCRIPT_PATH.exists():
    pytest.skip(
        "match-token script has no equivalent in NexusCampaigns "
        "(pathway-specific utility; token matching handled by vision/token agents). "
        "Skip until a dedicated match-token tool is added under agents/.",
        allow_module_level=True,
    )

match_token = _load_module()


# ---------------------------------------------------------------------------
# Image factories - create minimal valid images for each test
# ---------------------------------------------------------------------------

def make_solid_rgba(
    path: Path,
    width: int = 64,
    height: int = 64,
    color: tuple[int, int, int, int] = (150, 100, 50, 255),
) -> Path:
    """Fully-opaque RGBA PNG - no transparent pixels."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (width, height), color=color).save(str(path), "PNG")
    return path


def make_token_png(
    path: Path,
    width: int = 64,
    height: int = 64,
    content_color: tuple[int, int, int] = (150, 100, 50),
) -> Path:
    """Circular token: opaque inscribed circle on transparent background."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cx, cy = width // 2, height // 2
    r = min(cx, cy) - 2
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2:
                arr[y, x] = (*content_color, 255)
    Image.fromarray(arr, "RGBA").save(str(path), "PNG")
    return path


def make_rgb_png(
    path: Path,
    width: int = 64,
    height: int = 64,
    color: tuple[int, int, int] = (100, 150, 200),
) -> Path:
    """Solid RGB PNG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=color).save(str(path), "PNG")
    return path


def make_jpg(
    path: Path,
    width: int = 64,
    height: int = 64,
    color: tuple[int, int, int] = (200, 100, 50),
) -> Path:
    """Solid JPEG."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=color).save(str(path), "JPEG")
    return path


# ---------------------------------------------------------------------------
# _FakeHash - integer-backed stand-in for imagehash hash objects
# Subtraction returns the absolute difference between integer values.
# ---------------------------------------------------------------------------

class _FakeHash:
    def __init__(self, value: int) -> None:
        self._v = value

    def __sub__(self, other: "_FakeHash") -> int:
        return abs(self._v - other._v)

    def __rsub__(self, other: "_FakeHash") -> int:  # noqa: PLR0206
        return abs(other._v - self._v)


def _imagehash_mock(token_value: int, cand_values: list[int]) -> MagicMock:
    """
    Fake imagehash module.

    phash() call order: token_content, then 2 calls per candidate (full + crop).
    Distance = |token_value - cand_value|.
    """
    mock_ih = MagicMock()
    side = [_FakeHash(token_value)]
    for v in cand_values:
        side += [_FakeHash(v), _FakeHash(v)]  # full image + crop, same hash
    mock_ih.phash.side_effect = side
    return mock_ih


# ---------------------------------------------------------------------------
# face_recognition mock helpers
# ---------------------------------------------------------------------------

_DUMMY_ENC = np.array([0.1] * 128)


def _fr_happy(distance: float = 0.3) -> MagicMock:
    """Happy-path face_recognition: token + all candidates have one face each."""
    mock_fr = MagicMock()
    mock_fr.load_image_file.return_value = np.zeros((64, 64, 3), dtype=np.uint8)
    mock_fr.face_encodings.return_value = [_DUMMY_ENC]
    mock_fr.face_distance.return_value = np.array([distance])
    return mock_fr


def _fr_no_face() -> MagicMock:
    """face_recognition where every face_encodings call returns empty list."""
    mock_fr = MagicMock()
    mock_fr.load_image_file.return_value = np.zeros((64, 64, 3), dtype=np.uint8)
    mock_fr.face_encodings.return_value = []
    return mock_fr


def _fr_candidate_no_face() -> MagicMock:
    """Token has face; all candidates are faceless."""
    mock_fr = MagicMock()
    mock_fr.load_image_file.return_value = np.zeros((64, 64, 3), dtype=np.uint8)
    call_n = {"n": 0}

    def enc_side(*args, **kwargs):
        call_n["n"] += 1
        return [_DUMMY_ENC] if call_n["n"] == 1 else []

    mock_fr.face_encodings.side_effect = enc_side
    mock_fr.face_distance.return_value = np.array([0.3])
    return mock_fr


# ===========================================================================
# 1. _crop_circle_content
# ===========================================================================


class TestCropCircleContent:
    """_crop_circle_content: extract inscribed square by removing transparent frame."""

    def test_returns_rgb_image(self, tmp_path: Path) -> None:
        """Result is always PIL Image in RGB mode."""
        src = make_token_png(tmp_path / "token.png")
        result = match_token._crop_circle_content(src)
        assert isinstance(result, Image.Image)
        assert result.mode == "RGB"

    def test_solid_opaque_preserves_dimensions(self, tmp_path: Path) -> None:
        """Fully-opaque RGBA → bounding box equals full image, no crop."""
        src = make_solid_rgba(tmp_path / "solid.png", 64, 64)
        assert match_token._crop_circle_content(src).size == (64, 64)

    def test_circular_token_is_cropped(self, tmp_path: Path) -> None:
        """Circular token with transparent corners → result smaller than original."""
        src = make_token_png(tmp_path / "token.png", 64, 64)
        w, h = match_token._crop_circle_content(src).size
        assert w < 64 and h < 64

    def test_fully_transparent_no_crash(self, tmp_path: Path) -> None:
        """All-transparent PNG → returns full image as RGB fallback without raising."""
        path = tmp_path / "blank.png"
        Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(str(path), "PNG")
        result = match_token._crop_circle_content(path)
        assert result.mode == "RGB"

    def test_result_always_positive_size(self, tmp_path: Path) -> None:
        """Width and height of result are always > 0."""
        for i, src in enumerate([
            make_token_png(tmp_path / "a.png", 64, 64),
            make_solid_rgba(tmp_path / "b.png", 32, 32),
        ]):
            w, h = match_token._crop_circle_content(src).size
            assert w > 0 and h > 0, f"src {i}: got {(w, h)}"

    @pytest.mark.parametrize("width,height", [
        (16, 16),
        (32, 32),
        (64, 64),
        (128, 128),
        (48, 96),
    ])
    def test_various_sizes_no_crash(self, tmp_path: Path, width: int, height: int) -> None:
        """No crash and positive output dimensions for various image sizes."""
        src = make_token_png(tmp_path / f"t{width}x{height}.png", width, height)
        w, h = match_token._crop_circle_content(src).size
        assert w > 0 and h > 0


# ===========================================================================
# 2. _match_imagehash
# ===========================================================================


class TestMatchImageHash:
    """_match_imagehash: perceptual-hash matching with mocked imagehash library."""

    def test_identical_hash_returns_match(self, tmp_path: Path) -> None:
        """Hash distance 0 → (cand_path, 0, None)."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"imagehash": _imagehash_mock(100, [100])}):
            path, dist, err = match_token._match_imagehash(token, [cand], threshold=20)

        assert err is None
        assert path == cand
        assert dist == 0

    def test_distance_below_threshold_matches(self, tmp_path: Path) -> None:
        """Distance 10 < threshold 20 → match returned."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"imagehash": _imagehash_mock(100, [110])}):
            path, dist, err = match_token._match_imagehash(token, [cand], threshold=20)

        assert err is None
        assert path == cand
        assert dist == 10

    def test_distance_above_threshold_no_match(self, tmp_path: Path) -> None:
        """Distance 30 > threshold 20 → (None, None, error_string)."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"imagehash": _imagehash_mock(0, [30])}):
            path, dist, err = match_token._match_imagehash(token, [cand], threshold=20)

        assert path is None
        assert "exceeds threshold" in err

    def test_empty_candidates_returns_error(self, tmp_path: Path) -> None:
        """Empty candidates list → (None, None, 'no candidates processed')."""
        token = make_token_png(tmp_path / "token.png")

        with patch.dict(sys.modules, {"imagehash": _imagehash_mock(0, [])}):
            path, dist, err = match_token._match_imagehash(token, [], threshold=20)

        assert path is None
        assert "no candidates" in err

    def test_best_candidate_selected(self, tmp_path: Path) -> None:
        """Multiple candidates → one with minimum hash distance is returned."""
        token = make_token_png(tmp_path / "token.png")
        c_far = make_rgb_png(tmp_path / "far.png", color=(0, 0, 200))
        c_near = make_rgb_png(tmp_path / "near.png", color=(200, 0, 0))
        # token=100: c_far dist=15, c_near dist=2 → c_near wins
        mock_ih = _imagehash_mock(100, [115, 102])

        with patch.dict(sys.modules, {"imagehash": mock_ih}):
            path, dist, err = match_token._match_imagehash(
                token, [c_far, c_near], threshold=20
            )

        assert path == c_near
        assert dist == 2

    def test_broken_candidate_skipped(self, tmp_path: Path) -> None:
        """Candidate that PIL cannot open is skipped; remaining candidates processed."""
        token = make_token_png(tmp_path / "token.png")
        bad = tmp_path / "ghost.png"       # does not exist → PIL.open raises
        good = make_rgb_png(tmp_path / "good.png")
        mock_ih = _imagehash_mock(100, [100])  # good cand: distance 0

        with patch.dict(sys.modules, {"imagehash": mock_ih}):
            path, dist, err = match_token._match_imagehash(
                token, [bad, good], threshold=20
            )

        assert path == good

    @pytest.mark.parametrize("threshold,distance,should_match", [
        (5, 3, True),
        (5, 5, True),    # equal: not strictly greater → match
        (5, 6, False),
        (20, 19, True),
        (20, 20, True),
        (20, 21, False),
    ])
    def test_threshold_boundary(
        self,
        tmp_path: Path,
        threshold: int,
        distance: int,
        should_match: bool,
    ) -> None:
        """dist <= threshold → match; dist > threshold → no match."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"imagehash": _imagehash_mock(0, [distance])}):
            path, dist, err = match_token._match_imagehash(
                token, [cand], threshold=threshold
            )

        if should_match:
            assert path == cand, f"dist={distance} threshold={threshold}: expected match"
            assert err is None
        else:
            assert path is None, f"dist={distance} threshold={threshold}: expected no match"
            assert err is not None


# ===========================================================================
# 3. _match_face_recognition
# ===========================================================================


class TestMatchFaceRecognition:
    """_match_face_recognition: face-encoding matching with mocked face_recognition."""

    def test_happy_path_returns_match(self, tmp_path: Path) -> None:
        """Face found; distance below threshold → (cand_path, dist, None)."""
        token = make_rgb_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"face_recognition": _fr_happy(distance=0.3)}):
            path, dist, err = match_token._match_face_recognition(
                token, [cand], threshold=0.6
            )

        assert err is None
        assert path == cand
        assert dist == pytest.approx(0.3, abs=1e-4)

    def test_no_face_in_token(self, tmp_path: Path) -> None:
        """Token yields no face encodings (even after upsample retry) → error."""
        token = make_rgb_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"face_recognition": _fr_no_face()}):
            path, dist, err = match_token._match_face_recognition(
                token, [cand], threshold=0.6
            )

        assert path is None
        assert dist is None
        assert "no face detected" in err

    def test_no_face_in_any_candidate(self, tmp_path: Path) -> None:
        """Token OK; all candidates faceless → 'no face found in any candidate'."""
        token = make_rgb_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"face_recognition": _fr_candidate_no_face()}):
            path, dist, err = match_token._match_face_recognition(
                token, [cand], threshold=0.6
            )

        assert path is None
        assert "no face found" in err

    def test_distance_exceeds_threshold(self, tmp_path: Path) -> None:
        """Distance > threshold → (None, None, 'exceeds threshold ...')."""
        token = make_rgb_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"face_recognition": _fr_happy(distance=0.9)}):
            path, dist, err = match_token._match_face_recognition(
                token, [cand], threshold=0.6
            )

        assert path is None
        assert "exceeds threshold" in err

    def test_best_of_multiple_candidates(self, tmp_path: Path) -> None:
        """Multiple candidates → closest face distance wins."""
        token = make_rgb_png(tmp_path / "token.png")
        c1 = make_rgb_png(tmp_path / "c1.png", color=(100, 0, 0))
        c2 = make_rgb_png(tmp_path / "c2.png", color=(0, 100, 0))

        mock_fr = MagicMock()
        mock_fr.load_image_file.return_value = np.zeros((64, 64, 3), dtype=np.uint8)
        mock_fr.face_encodings.return_value = [_DUMMY_ENC]
        dist_seq = iter([0.7, 0.2])   # c1 far, c2 close
        mock_fr.face_distance.side_effect = lambda enc_list, enc: np.array([next(dist_seq)])

        with patch.dict(sys.modules, {"face_recognition": mock_fr}):
            path, dist, err = match_token._match_face_recognition(
                token, [c1, c2], threshold=0.6
            )

        assert path == c2
        assert dist == pytest.approx(0.2, abs=1e-4)

    def test_candidate_exception_gracefully_skipped(self, tmp_path: Path) -> None:
        """Candidate that raises on load_image_file is skipped; others still work."""
        token = make_rgb_png(tmp_path / "token.png")
        bad = tmp_path / "ghost.png"
        good = make_rgb_png(tmp_path / "good.png")

        mock_fr = MagicMock()
        load_n = {"n": 0}

        def load_side(p):
            load_n["n"] += 1
            if load_n["n"] == 1:
                return np.zeros((64, 64, 3), dtype=np.uint8)  # token
            if str(p) == str(bad):
                raise FileNotFoundError("not found")
            return np.zeros((64, 64, 3), dtype=np.uint8)  # good cand

        mock_fr.load_image_file.side_effect = load_side
        mock_fr.face_encodings.return_value = [_DUMMY_ENC]
        mock_fr.face_distance.return_value = np.array([0.3])

        with patch.dict(sys.modules, {"face_recognition": mock_fr}):
            path, dist, err = match_token._match_face_recognition(
                token, [bad, good], threshold=0.6
            )

        assert path == good
        assert err is None

    @pytest.mark.parametrize("threshold,distance,should_match", [
        (0.6, 0.3, True),
        (0.6, 0.6, True),    # equal: not strictly greater → match
        (0.6, 0.7, False),
        (0.3, 0.2, True),
        (0.3, 0.3, True),
        (0.3, 0.4, False),
    ])
    def test_threshold_boundary(
        self,
        tmp_path: Path,
        threshold: float,
        distance: float,
        should_match: bool,
    ) -> None:
        """dist <= threshold → match; dist > threshold → no match."""
        token = make_rgb_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        with patch.dict(sys.modules, {"face_recognition": _fr_happy(distance=distance)}):
            path, dist, err = match_token._match_face_recognition(
                token, [cand], threshold=threshold
            )

        if should_match:
            assert path == cand, f"dist={distance} threshold={threshold}: expected match"
        else:
            assert path is None, f"dist={distance} threshold={threshold}: expected no match"


# ===========================================================================
# 4. main() - CLI contract via subprocess
# ===========================================================================


class TestMainCLI:
    """End-to-end CLI tests: script invoked as subprocess, JSON stdout validated."""

    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    # --- missing / invalid inputs -------------------------------------------

    def test_missing_token_null_match(self, tmp_path: Path) -> None:
        """Non-existent --token path → {match: null, reason: 'token not found:...'}"""
        cand = make_rgb_png(tmp_path / "cand.png")
        out = json.loads(self._run(
            "--token", str(tmp_path / "ghost.png"),
            "--candidates", str(cand),
            "--method", "imagehash",
        ).stdout)
        assert out["match"] is None
        assert "not found" in out.get("reason", "")

    def test_no_valid_candidates_null_match(self, tmp_path: Path) -> None:
        """All --candidates paths non-existent → {match: null, reason: 'no valid...'}"""
        token = make_token_png(tmp_path / "token.png")
        out = json.loads(self._run(
            "--token", str(token),
            "--candidates", str(tmp_path / "g1.png"), str(tmp_path / "g2.png"),
            "--method", "imagehash",
        ).stdout)
        assert out["match"] is None
        assert "no valid candidate" in out.get("reason", "")

    @pytest.mark.parametrize("args", [
        ["--candidates", "x.png"],   # --token missing
        ["--token", "x.png"],        # --candidates missing
    ])
    def test_missing_required_arg_nonzero_exit(self, args: list[str]) -> None:
        """argparse exits non-zero when a required argument is absent."""
        assert self._run(*args).returncode != 0

    # --- JSON contract -------------------------------------------------------

    @_skip_no_imagehash
    def test_stdout_is_valid_json(self, tmp_path: Path) -> None:
        """Any invocation produces parseable JSON on stdout."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")
        raw = self._run(
            "--token", str(token),
            "--candidates", str(cand),
            "--method", "imagehash",
        ).stdout
        assert isinstance(json.loads(raw), dict)

    @_skip_no_imagehash
    def test_match_key_always_present(self, tmp_path: Path) -> None:
        """'match' key always present regardless of outcome."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")
        out = json.loads(self._run(
            "--token", str(token),
            "--candidates", str(cand),
            "--method", "imagehash",
        ).stdout)
        assert "match" in out

    @_skip_no_imagehash
    def test_exit_code_zero_happy(self, tmp_path: Path) -> None:
        """Exit 0 when token + candidate both exist."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")
        assert self._run(
            "--token", str(token),
            "--candidates", str(cand),
            "--method", "imagehash",
        ).returncode == 0

    def test_exit_code_zero_on_no_match(self, tmp_path: Path) -> None:
        """Exit 0 even when the token path itself is missing."""
        assert self._run(
            "--token", str("ghost.png"),
            "--candidates", "also_ghost.png",
            "--method", "imagehash",
        ).returncode == 0

    @_skip_no_imagehash
    def test_successful_match_has_method_field(self, tmp_path: Path) -> None:
        """When match is found, JSON includes 'method': 'imagehash'."""
        # Identical solid RGBA → identical phash → distance 0 → should match
        t = tmp_path / "token.png"
        c = tmp_path / "cand.png"
        Image.new("RGBA", (64, 64), (128, 64, 32, 255)).save(str(t), "PNG")
        Image.new("RGB",  (64, 64), (128, 64, 32)).save(str(c), "PNG")

        out = json.loads(self._run(
            "--token", str(t),
            "--candidates", str(c),
            "--method", "imagehash",
        ).stdout)
        if out.get("match") is not None:
            assert out["method"] == "imagehash"

    # --- method flag --------------------------------------------------------

    @_skip_no_imagehash
    def test_explicit_imagehash_method(self, tmp_path: Path) -> None:
        """--method imagehash runs without error when imagehash is available."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")
        result = self._run(
            "--token", str(token),
            "--candidates", str(cand),
            "--method", "imagehash",
        )
        assert result.returncode == 0
        json.loads(result.stdout)  # must be valid JSON

    def test_no_library_outputs_pip_hint(self, tmp_path: Path) -> None:
        """When neither face_recognition nor imagehash importable → reason includes pip."""
        token = make_token_png(tmp_path / "token.png")
        cand = make_rgb_png(tmp_path / "cand.png")

        blocker = (
            "import builtins\n"
            "_orig = builtins.__import__\n"
            "def _block(name, *a, **kw):\n"
            "    if name in ('face_recognition', 'imagehash'):\n"
            "        raise ImportError(name)\n"
            "    return _orig(name, *a, **kw)\n"
            "builtins.__import__ = _block\n"
            f"import sys; sys.argv = ['06-match-token.py', '--token', r'{token}', "
            f"'--candidates', r'{cand}']\n"
            f"exec(open(r'{SCRIPT_PATH}').read())\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", blocker],
            capture_output=True,
            text=True,
            timeout=15,
        )
        out = json.loads(result.stdout)
        assert out["match"] is None
        assert "pip install" in out.get("reason", "")


# ===========================================================================
# 5. Parametrized multi-format / multi-candidate edge cases
# ===========================================================================


@pytest.mark.parametrize("ext,factory", [
    (".png", make_rgb_png),
    (".jpg", make_jpg),
])
def test_imagehash_accepts_different_formats(
    tmp_path: Path, ext: str, factory
) -> None:
    """_match_imagehash accepts PNG and JPEG candidate files without error."""
    token = make_token_png(tmp_path / "token.png")
    cand = factory(tmp_path / f"cand{ext}")
    mock_ih = _imagehash_mock(100, [100])

    with patch.dict(sys.modules, {"imagehash": mock_ih}):
        path, dist, err = match_token._match_imagehash(token, [cand], threshold=20)

    # Should either match or return a structured error - never raise
    assert isinstance(path, (Path, type(None)))


@pytest.mark.parametrize("n_candidates", [1, 3, 5])
def test_imagehash_multiple_candidates(tmp_path: Path, n_candidates: int) -> None:
    """_match_imagehash handles arbitrary number of candidates."""
    token = make_token_png(tmp_path / "token.png")
    cands = [make_rgb_png(tmp_path / f"c{i}.png") for i in range(n_candidates)]
    # All candidates at distance 5; threshold 20 → all match, first one stored as best
    mock_ih = _imagehash_mock(100, [105] * n_candidates)

    with patch.dict(sys.modules, {"imagehash": mock_ih}):
        path, dist, err = match_token._match_imagehash(token, cands, threshold=20)

    assert err is None
    assert path in cands
    assert dist == 5

