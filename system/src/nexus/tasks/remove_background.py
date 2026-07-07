"""nexus.tasks.remove_background

Turn glow-on-dark logo / emblem art into transparent PNGs, plus an optional
"filled shape" variant that keeps the interior background color of an enclosed
emblem (e.g. a heraldic shield) instead of dropping it.

Source art (e.g. system/assets/*.jpg) is a bright, glowing subject on a
near-black / dark-navy background. A hard AI cutout would clip the soft glow
halos, so this uses *luminance + color keying*:

  method = "hybrid"  -> color distance keeps the saturated subject solid
                        AND luminance keeps the soft glow (default)
  method = "luma"    -> alpha from luminance only (glow-only, ghostly)
  method = "color"   -> alpha from color distance only (hard cutout)

The "fill_shield" tool segments the closed bright outline of an emblem, fills
the enclosed interior, and keeps the original colors inside the silhouette.

No LLM. Pure image processing (numpy + Pillow + OpenCV).

Config: every tunable comes from system/state/token/bg-config.json
(falls back to _DEFAULT_CFG below).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from nexus.shared.logger import Logger, _ensure_utf8_stdout
from nexus.shared.loaders import _find_project_root

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

TASK_ID         = "token-agent"
SCRIPT_BASENAME = "remove_background.py"

_STATE_ROOT   = _PROJECT_ROOT / "system" / "state"
_AGENT_STATE  = _STATE_ROOT / "token"
_BG_CONFIG    = _AGENT_STATE / "bg-config.json"
_LOGS_DIR     = _AGENT_STATE / "logs"
_MASTER_LOG   = _STATE_ROOT / "runtime" / "logs" / "automation.log"

# Rec.709 luminance weights (perceptual brightness)
_LUMA_W = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# --------------------------------------------------------------------------
# Configuration — defaults; live values come from system/state/token/bg-config.json
# --------------------------------------------------------------------------
_DEFAULT_CFG: dict[str, Any] = {
    "method":        "hybrid",   # hybrid | luma | color
    "margin":        0.06,       # distance above bg floor before pixels show
    "gamma":         0.85,       # alpha curve; <1 keeps glow, >1 hardens edges
    "floor":         None,       # override bg luminance [0..1]; None = auto
    "defringe":      True,       # strip dark-bg tint from soft edges
    "trim":          False,      # autocrop to content bounding box
    "border_sample": 6,          # px frame used to measure background
    "input_dir":     "system/assets",
    "output_dir":    "system/assets/transparent",
    "supported_ext": [".jpg", ".jpeg", ".png", ".webp", ".bmp"],
    "fill_suffix":       "-shield",  # output suffix for filled-shape variant
    "fill_threshold":    0.18,       # luminance threshold for the bright outline
    "fill_close_radius": 4,          # dilation radius (px) to close outline gaps
    "fill_feather":      1.5,        # gaussian blur (px) on the filled-shape edge
}


def _load_config() -> dict[str, Any]:
    """Read bg-config.json (optional), merged over defaults."""
    cfg = dict(_DEFAULT_CFG)
    if _BG_CONFIG.exists():
        try:
            stored = json.loads(_BG_CONFIG.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                cfg.update(stored)
        except Exception:
            pass
    return cfg


# Loaded once at import — every variable below originates from agent config
CONFIG        = _load_config()
METHOD        = CONFIG["method"]
MARGIN        = float(CONFIG["margin"])
GAMMA         = float(CONFIG["gamma"])
FLOOR         = CONFIG["floor"]
DEFRINGE      = bool(CONFIG["defringe"])
TRIM          = bool(CONFIG["trim"])
BORDER_SAMPLE = int(CONFIG["border_sample"])
INPUT_DIR     = (_PROJECT_ROOT / CONFIG["input_dir"]).resolve()
OUTPUT_DIR    = (_PROJECT_ROOT / CONFIG["output_dir"]).resolve()
SUPPORTED     = {e.lower() for e in CONFIG["supported_ext"]}
FILL_SUFFIX        = CONFIG["fill_suffix"]
FILL_THRESHOLD     = float(CONFIG["fill_threshold"])
FILL_CLOSE_RADIUS  = int(CONFIG["fill_close_radius"])
FILL_FEATHER       = float(CONFIG["fill_feather"])


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


# --------------------------------------------------------------------------
# Keying primitives
# --------------------------------------------------------------------------

def _luminance(rgb: np.ndarray) -> np.ndarray:
    """Perceptual luminance in [0,1] from HxWx3 float array in [0,1]."""
    return rgb @ _LUMA_W


def _border_pixels(arr: np.ndarray, border: int) -> np.ndarray:
    """Flattened frame of border pixels (works for HxW or HxWxC)."""
    h, w = arr.shape[:2]
    b = max(1, min(border, h // 4, w // 4))
    parts = [arr[:b], arr[-b:], arr[:, :b], arr[:, -b:]]
    flat = [p.reshape(-1, arr.shape[2]) if arr.ndim == 3 else p.ravel() for p in parts]
    return np.concatenate(flat, axis=0)


def _estimate_floor(lum: np.ndarray, border: int) -> float:
    """Background luminance from the border frame (90th pct tolerates gradients)."""
    return float(np.percentile(_border_pixels(lum, border), 90))


def _estimate_bg_color(rgb: np.ndarray, border: int) -> np.ndarray:
    """Median background color from the border frame -> (3,)."""
    return np.median(_border_pixels(rgb, border), axis=0).astype(np.float32)


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _alpha_from_luma(rgb: np.ndarray, floor: float, margin: float) -> np.ndarray:
    """Alpha from luminance — captures soft glow halos as they fade to dark."""
    lum = _luminance(rgb)
    lo = min(0.95, floor + margin)
    hi = max(lo + 1e-3, float(np.percentile(lum, 99.5)))
    return _smoothstep((lum - lo) / (hi - lo))


def _alpha_from_color(rgb: np.ndarray, bg_rgb: np.ndarray, margin: float) -> np.ndarray:
    """Alpha from color distance to bg — keeps the saturated subject solid."""
    dist = np.linalg.norm(rgb - bg_rgb[None, None, :], axis=2) / np.sqrt(3.0)
    lo = margin
    hi = max(lo + 1e-3, float(np.percentile(dist, 99.5)))
    return _smoothstep((dist - lo) / (hi - lo))


def _make_alpha(rgb, floor, bg_rgb, method, margin, gamma) -> np.ndarray:
    luma = _alpha_from_luma(rgb, floor, margin)
    if method == "luma":
        a = luma
    elif method == "color":
        a = _alpha_from_color(rgb, bg_rgb, margin)
    else:  # hybrid: solid subject (color) + soft glow (luma)
        a = np.maximum(_alpha_from_color(rgb, bg_rgb, margin), luma)
    if gamma != 1.0:
        a = np.power(np.clip(a, 0.0, 1.0), gamma)
    return a


def _unmultiply_fringe(rgb: np.ndarray, alpha: np.ndarray, floor: float) -> np.ndarray:
    """Remove dark-bg tint bleeding into semi-transparent edges, then renormalize."""
    a = alpha[..., None]
    out = rgb - (1.0 - a) * np.float32(floor)
    return np.clip(out / np.clip(a, 1e-3, 1.0), 0.0, 1.0)


def _trim_to_content(rgba: np.ndarray, thresh: float = 0.04, pad: int = 8) -> np.ndarray:
    a = rgba[..., 3]
    ys, xs = np.where(a > thresh * 255)
    if ys.size == 0:
        return rgba
    h, w = a.shape
    y0 = max(0, ys.min() - pad); x0 = max(0, xs.min() - pad)
    y1 = min(h - 1, ys.max() + pad); x1 = min(w - 1, xs.max() + pad)
    return rgba[y0:y1 + 1, x0:x1 + 1]


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------

def remove_bg(src: Path, dest: Path, *, method=None, margin=None, gamma=None,
              floor=None, defringe=None, trim=None) -> dict:
    """Write an RGBA PNG of `src` with the dark background keyed out."""
    from PIL import Image

    method   = method   if method   is not None else METHOD
    margin   = margin   if margin   is not None else MARGIN
    gamma    = gamma    if gamma    is not None else GAMMA
    floor_ov = floor    if floor    is not None else FLOOR
    defringe = defringe if defringe is not None else DEFRINGE
    trim     = trim     if trim     is not None else TRIM

    rgb = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32) / 255.0
    lum = _luminance(rgb)
    bg_floor = float(floor_ov) if floor_ov is not None else _estimate_floor(lum, BORDER_SAMPLE)
    bg_rgb   = _estimate_bg_color(rgb, BORDER_SAMPLE)

    alpha = _make_alpha(rgb, bg_floor, bg_rgb, method, margin, gamma)
    if defringe:
        rgb = _unmultiply_fringe(rgb, alpha, bg_floor)

    rgba = (np.clip(np.dstack([rgb, alpha]), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    if trim:
        rgba = _trim_to_content(rgba)

    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(dest)
    return {
        "floor": round(bg_floor, 4),
        "opaque_pct": round(100.0 * float((rgba[..., 3] > 127).mean()), 1),
        "size": f"{rgba.shape[1]}x{rgba.shape[0]}",
    }


def fill_shape(src: Path, dest: Path, *, threshold=None, close_radius=None,
               feather=None) -> dict:
    """
    Keep the interior background color of an enclosed emblem (e.g. a shield).
    Detects the bright outline, fills the enclosed silhouette, keeps original
    colors inside, transparent outside.
    """
    import cv2
    from PIL import Image

    threshold    = threshold    if threshold    is not None else FILL_THRESHOLD
    close_radius = close_radius if close_radius is not None else FILL_CLOSE_RADIUS
    feather      = feather      if feather      is not None else FILL_FEATHER

    rgb = np.asarray(Image.open(src).convert("RGB"))
    lum = (rgb.astype(np.float32) / 255.0) @ _LUMA_W
    h, w = lum.shape

    border = ((lum > threshold) * 255).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * close_radius + 1,) * 2)
    closed = cv2.dilate(border, k)                       # close outline gaps

    ff = closed.copy()
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)
    holes  = cv2.bitwise_not(ff)                         # enclosed interior
    filled = cv2.erode(cv2.bitwise_or(closed, holes), k)  # undo dilation growth

    cnts, _ = cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(filled)
    if cnts:
        cv2.drawContours(mask, [max(cnts, key=cv2.contourArea)], -1, 255, -1)
    alpha = cv2.GaussianBlur(mask, (0, 0), feather) if feather > 0 else mask

    rgba = np.dstack([rgb, alpha]).astype(np.uint8)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(dest)
    return {
        "shape_pct": round(100.0 * float((mask > 0).mean()), 1),
        "size": f"{w}x{h}",
    }


def _collect_inputs(items: list[str] | None) -> list[Path]:
    if not items:
        if not INPUT_DIR.is_dir():
            return []
        return sorted(p for p in INPUT_DIR.iterdir() if p.suffix.lower() in SUPPORTED)
    out: list[Path] = []
    for it in items:
        p = Path(it)
        if not p.is_absolute():
            p = (INPUT_DIR / it) if (INPUT_DIR / it).exists() else (_PROJECT_ROOT / it)
        if p.is_dir():
            out.extend(sorted(q for q in p.iterdir() if q.suffix.lower() in SUPPORTED))
        elif p.exists():
            out.append(p)
    return out


def _out_path(src: Path) -> Path:
    return OUTPUT_DIR / (src.stem + ".png")


# --------------------------------------------------------------------------
# CLI entry (also used by call_tool batch)
# --------------------------------------------------------------------------

def main(inputs: list[str] | None = None) -> None:
    _ensure_utf8_stdout()
    log = _make_logger()
    t0 = log.start()

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        log.error("Pillow not installed — install: pip install Pillow")
        log.done(t0, key="processed", count=0, failed=0)
        sys.exit(1)

    files = _collect_inputs(inputs)
    if not files:
        log.info(f"No input images in {INPUT_DIR}")
        log.done(t0, key="processed", count=0, failed=0)
        sys.exit(0)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"method={METHOD} -> {OUTPUT_DIR} ({len(files)} image(s))")
    count = failed = 0
    for src in files:
        try:
            stats = remove_bg(src, _out_path(src))
            log.info(f"{src.name} -> {src.stem}.png "
                     f"[floor={stats['floor']} opaque={stats['opaque_pct']}% {stats['size']}]")
            count += 1
        except Exception as exc:
            log.error(f"Failed {src.name}: {exc}")
            failed += 1

    log.done(t0, key="processed", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


def _resolve(image_path: str) -> Path:
    p = Path(image_path)
    if not p.is_absolute():
        cand = INPUT_DIR / image_path
        p = cand if cand.exists() else _PROJECT_ROOT / image_path
    return p


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Background removal / shape fill (config: bg-config.json)")
    ap.add_argument("inputs", nargs="*", help="files/dirs (default: configured input_dir)")
    ap.add_argument("--fill", metavar="IMAGE", help="fill enclosed emblem interior instead of removing bg")
    a = ap.parse_args()
    if a.fill:
        _ensure_utf8_stdout()
        src = _resolve(a.fill)
        dest = OUTPUT_DIR / (src.stem + FILL_SUFFIX + ".png")
        st = fill_shape(src, dest)
        print(f"{dest} [shape={st['shape_pct']}% {st['size']}]")
    else:
        main(a.inputs or None)
