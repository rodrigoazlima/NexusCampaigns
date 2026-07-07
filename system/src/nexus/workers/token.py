"""nexus.workers.token — VTT token generator (queue consumer).

Generates 512×512 circular portrait tokens from vision-classified images.
Face detection: MTCNN (robust on stylized art) → OpenCV Haar (topmost) →
upper-center crop fallback. Moldura ring composed on top, inner radius
auto-detected from the frame's alpha channel; per-type override via
options.moldura_by_type. Output next to source as <stem>-token.png.
Replaces nexus.tasks.generate_tokens.

Carried-over safeguards:
  - purges stale generated-tokens entries whose tokenPath is gone
  - never processes stems ending -token / containing .token
  - stores the detected face box back into vision state via _store_face
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nexus.shared import locked_update_queue_entry
from nexus.shared.loaders import _find_project_root
from nexus.shared.logger import Logger
from nexus.workers.base import (
    WORKERS_STATE_ROOT,
    WorkItem,
    WorkResult,
    adopt_legacy_file,
    make_worker_logger,
)

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

_STATE_ROOT   = _PROJECT_ROOT / "system" / "state"
_VISION_STATE = _PROJECT_ROOT / "agents" / "vision" / "state" / "processed-images.json"
_QUEUE_FILE   = _STATE_ROOT / "inbox-queue.json"

_WORKER_STATE = WORKERS_STATE_ROOT / "token"
_GEN_TOKENS   = _WORKER_STATE / "generated-tokens.json"
_CONFIG_FILE  = _WORKER_STATE / "10-generate-tokens.json"

# Legacy homes (nexus.tasks.generate_tokens wrote system/state/token; the
# deployed pipeline wrote agents/token/state) — adopted once, then unused
_LEGACY_STATE_DIRS = (
    _STATE_ROOT / "token",
    _PROJECT_ROOT / "agents" / "token" / "state",
)

_DEFAULT_CFG: dict[str, Any] = {
    "size":           512,
    "padding":        0.18,       # fraction of inner circle diameter (0–0.49)
    "forehead_ratio": 0.35,       # extra head room above face bbox top
    "body_ratio":     0.30,       # extra body room below face bbox bottom
    "focus_head":     [0, 0, 0, 0],  # [top, right, bottom, left] % of crop_size
    "moldura_path":   ".knowledge-base/05-Assets/tokens/frames/frame.png",
    "moldura_by_type": {},        # e.g. {"creature": "path/to/creature_frame.png"}
}

_SKIP_TYPES = frozenset({"battlemap", "scene"})
_MAX_RERUNS = 3   # poison-pill guard (worker-contract.spec.md)

_warned_no_pillow = False


def _adopt_legacy_state() -> None:
    for legacy in _LEGACY_STATE_DIRS:
        adopt_legacy_file(legacy / "generated-tokens.json", _GEN_TOKENS)
        adopt_legacy_file(legacy / "10-generate-tokens.json", _CONFIG_FILE)


def _is_token_stem(p: Path) -> bool:
    stem = p.stem
    return stem.endswith("-token") or ".token" in stem


def _load_config(options: dict | None = None) -> dict[str, Any]:
    cfg = dict(_DEFAULT_CFG)
    if _CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(_CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    else:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(_DEFAULT_CFG, indent=2), encoding="utf-8")
    # registry.yaml worker options override file config (moldura_by_type etc.)
    cfg.update(options or {})
    return cfg


def _load_vision_state() -> dict[str, Any]:
    if not _VISION_STATE.exists():
        return {"images": {}, "pathIndex": {}}
    return json.loads(_VISION_STATE.read_text(encoding="utf-8"))


def _store_face(src_rel: str, face: dict | None, log: Logger) -> None:
    """Persist the detected face position onto the source image's index entry in
    processed-images.json, so re-generation and the manual token editor can
    reuse it. No-op when no face or the image isn't indexed.

    ponytail: read-modify-write of the shared vision state — last writer wins. The
    vision agent runs hourly and rarely overlaps a manual token gen; if contention
    ever matters, gate both on a lock file.
    """
    if not face:
        return
    state = _load_vision_state()
    sha = state.get("pathIndex", {}).get(src_rel)
    entry = state.get("images", {}).get(sha) if sha and not str(sha).startswith("path:") else None
    if entry is None:
        return
    entry["face"] = face
    tmp = _VISION_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(_VISION_STATE)
    log.info(f"Stored face for {src_rel.split('/')[-1]}: center=({face['cx']},{face['cy']})")


def _load_gen_tokens() -> dict[str, Any]:
    if not _GEN_TOKENS.exists():
        return {}
    return json.loads(_GEN_TOKENS.read_text(encoding="utf-8"))


def _save_gen_tokens(data: dict) -> None:
    _GEN_TOKENS.parent.mkdir(parents=True, exist_ok=True)
    tmp = _GEN_TOKENS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(_GEN_TOKENS)


def _load_queue() -> dict[str, Any]:
    if not _QUEUE_FILE.exists():
        return {}
    try:
        return json.loads(_QUEUE_FILE.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception:
        return {}


def _set_queue_token_slot(source_rel: str, status: str, log: Logger) -> bool:
    queue = _load_queue()
    if source_rel not in queue:
        return False

    changed = False

    def _mark(entry: dict) -> Optional[str]:
        nonlocal changed
        agents = entry.setdefault("agents", {})
        if agents.get("token") != status:
            agents["token"] = status
            changed = True
        return None

    locked_update_queue_entry(_QUEUE_FILE, source_rel, _mark)
    if changed:
        log.info(f"Queue token slot [{status}]: {source_rel.split('/')[-1]}")
    return changed


def _pick_moldura(entry: dict[str, Any], cfg: dict[str, Any]) -> Path:
    """Resolve moldura path: per-type override from config, else default."""
    img_type = entry.get("type", "")
    by_type: dict = cfg.get("moldura_by_type", {})
    rel = by_type.get(img_type) or cfg.get("moldura_path", "")
    if not rel:
        return Path()
    p = Path(rel)
    return p if p.is_absolute() else _PROJECT_ROOT / rel


# ---------------------------------------------------------------------------
# Face detection  (returns center-point form: cx, cy, fw, fh)
# ---------------------------------------------------------------------------

_MTCNN_DETECTOR: Any = None


def _get_mtcnn() -> Any:
    """Lazily build + cache the MTCNN detector (network construction is expensive)."""
    global _MTCNN_DETECTOR
    if _MTCNN_DETECTOR is None:
        from mtcnn import MTCNN  # type: ignore[import]
        _MTCNN_DETECTOR = MTCNN()
    return _MTCNN_DETECTOR


def _detect_face_mtcnn(img_array: Any, min_conf: float = 0.90) -> tuple[int, int, int, int] | None:
    """Primary detector. Robust on stylized/illustrated fantasy art where Haar
    fires false positives on armor/belts/weapons. Expects an RGB array.
    Picks the highest-confidence face. Returns center-point form (cx, cy, fw, fh).
    """
    try:
        results = _get_mtcnn().detect_faces(img_array)
        if not results:
            return None
        best = max(results, key=lambda r: r.get("confidence", 0.0))
        if best.get("confidence", 0.0) < min_conf:
            return None
        x, y, fw, fh = best["box"]
        x, y = max(0, int(x)), max(0, int(y))
        return x + fw // 2, y + fh // 2, int(fw), int(fh)
    except Exception:
        return None


def _detect_face_opencv(img_array: Any) -> tuple[int, int, int, int] | None:
    try:
        import cv2  # type: ignore[import]
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        cascade_path = str(Path(__file__).parent / "haarcascade_frontalface_default.xml")
        if not Path(cascade_path).exists():
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        clf = cv2.CascadeClassifier(cascade_path)
        faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
        if not len(faces):
            return None
        # ponytail: pick the TOPMOST detection, not the largest. Haar fires false
        # positives on belts/gauntlets/weapons that are often bigger than the real
        # face; in a portrait the head sits highest, so smallest-y wins.
        x, y, fw, fh = min(faces, key=lambda f: f[1])
        cx = int(x) + fw // 2
        cy = int(y) + fh // 2
        return cx, cy, int(fw), int(fh)
    except Exception:
        return None


def _upper_center_crop(w: int, h: int, cfg: dict) -> tuple[int, int, int, int]:
    """Fallback: upper-center square crop when no face detected."""
    size = int(min(w, h) * 0.72)
    x = (w - size) // 2
    y = int(h * 0.05)
    return x, y, size, size


def _parse_focus_head(value: Any) -> tuple[float, float, float, float]:
    """CSS-like [top, right, bottom, left] in % of crop_size. Accepts array or legacy dict."""
    if value is None:
        return 0.0, 0.0, 0.0, 0.0
    if isinstance(value, dict):
        return (float(value.get("top", 0)), float(value.get("right", 0)),
                float(value.get("bottom", 0)), float(value.get("left", 0)))
    if isinstance(value, (int, float)):
        v = float(value)
        return v, v, v, v
    v = [float(x) for x in value]
    if len(v) == 1:
        return v[0], v[0], v[0], v[0]
    if len(v) == 2:
        return v[0], 0.0, 0.0, v[1]
    if len(v) == 3:
        return v[0], v[1], v[2], v[1]
    return v[0], v[1], v[2], v[3]


# ---------------------------------------------------------------------------
# Moldura geometry
# ---------------------------------------------------------------------------

def _detect_ring_radii(frame_arr: Any) -> tuple[int, int]:
    """Scan center row of alpha channel outward to find inner and outer ring radii."""
    H, W  = frame_arr.shape[:2]
    cx    = W // 2
    cy    = H // 2
    alpha = frame_arr[cy, :, 3]

    inner_r: int | None = None
    for x in range(cx, W):
        if alpha[x] > 128:
            inner_r = x - cx
            break

    outer_r: int | None = None
    for x in range(W - 1, cx, -1):
        if alpha[x] > 128:
            outer_r = x - cx
            break

    return inner_r or W // 4, outer_r or W // 2


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

def _make_token(img_path: Path, out_path: Path, cfg: dict, log: Logger,
                moldura_path: Path | None = None) -> tuple[bool, dict | None]:
    """Returns (ok, face) where face is the detected face position in SOURCE
    pixels — {cx, cy, w, h, img_w, img_h} — or None when no face was found
    (upper-center fallback was used)."""
    try:
        from PIL import Image, ImageDraw
        import numpy as np
    except ImportError:
        log.error("Pillow not installed — cannot generate tokens")
        return False, None

    try:
        # Resolve moldura
        frame_path = moldura_path if moldura_path and moldura_path.exists() else None
        if frame_path is None:
            rel = cfg.get("moldura_path", "")
            if rel:
                candidate = Path(rel) if Path(rel).is_absolute() else _PROJECT_ROOT / rel
                if candidate.exists():
                    frame_path = candidate

        out_size = cfg.get("size", 512)
        padding  = float(cfg.get("padding", 0.18))   # fraction

        # Load moldura and detect inner radius
        if frame_path and frame_path.exists():
            frame_full = Image.open(frame_path).convert("RGBA")
            frame      = frame_full.resize((out_size, out_size), Image.LANCZOS)
            frame_arr  = np.array(frame_full)
            inner_r_full, _ = _detect_ring_radii(frame_arr)
            scale_f = out_size / frame_full.width
            inner_r = int(inner_r_full * scale_f)
            char_r  = inner_r + 2   # slight overlap to sit flush under ring
            log.info(f"Moldura inner_r={inner_r}px from {frame_path.name}")
        else:
            frame     = None
            inner_r   = out_size // 2 - int(out_size * padding)
            char_r    = inner_r
            if frame_path:
                log.warning(f"Moldura not found: {frame_path}")

        # Load source
        img   = Image.open(img_path).convert("RGBA")
        w, h  = img.size
        arr   = np.array(img.convert("RGB"))
        IH, IW = arr.shape[:2]
        SRC_H, SRC_W = IH, IW  # original dims — IH/IW get mutated by padding below

        # Detect face (center-point form). MTCNN primary (handles stylized art),
        # Haar topmost fallback.
        face = _detect_face_mtcnn(arr) or _detect_face_opencv(arr)
        face_meta: dict | None = None
        if face:
            _fcx, _fcy, _fw, _fh = face
            face_meta = {"cx": int(_fcx), "cy": int(_fcy), "w": int(_fw), "h": int(_fh),
                         "img_w": int(SRC_W), "img_h": int(SRC_H)}

        forehead_ratio = float(cfg.get("forehead_ratio", 0.35))
        body_ratio     = float(cfg.get("body_ratio", 0.30))

        if face:
            fcx, fcy, fw, fh = face
            face_top  = fcy - fh // 2
            face_bot  = fcy + fh // 2
            head_top  = face_top - int(fh * forehead_ratio)
            body_bot  = face_bot  + int(fh * body_ratio)
            portrait_h = body_bot - head_top
            usable     = 1.0 - 2.0 * padding
            crop_size  = int(portrait_h / usable)
            crop_cy    = (head_top + body_bot) // 2
            crop_cx    = fcx
            log.info(f"Face detected: center=({fcx},{fcy}) size={fw}x{fh} "
                     f"head_top={head_top} body_bot={body_bot} crop={crop_size}px")
        else:
            log.info("No face detected — upper-center fallback")
            crop_x, crop_y, crop_size, _ = _upper_center_crop(IW, IH, cfg)
            crop_cx = crop_x + crop_size // 2
            crop_cy = crop_y + crop_size // 2

        # Apply focus_head offset
        fh_top, fh_right, fh_bottom, fh_left = _parse_focus_head(cfg.get("focus_head"))
        net_y = (fh_bottom - fh_top) / 100.0 * crop_size
        net_x = (fh_right  - fh_left) / 100.0 * crop_size
        if net_y or net_x:
            crop_cy += int(net_y)
            crop_cx += int(net_x)

        # Pad source if crop exceeds bounds
        half  = crop_size // 2
        pad_t = max(0, half - crop_cy)
        pad_b = max(0, (crop_cy + half) - IH)
        pad_l = max(0, half - crop_cx)
        pad_r = max(0, (crop_cx + half) - IW)

        if any([pad_t, pad_b, pad_l, pad_r]):
            arr     = np.pad(arr, ((pad_t, pad_b), (pad_l, pad_r), (0, 0)), mode="edge")
            crop_cy += pad_t
            crop_cx += pad_l
            IH, IW   = arr.shape[:2]

        # Crop square and scale to character disk
        y1 = max(0, crop_cy - half)
        y2 = min(IH, crop_cy + half)
        x1 = max(0, crop_cx - half)
        x2 = min(IW, crop_cx + half)
        cropped  = Image.fromarray(arr[y1:y2, x1:x2]).convert("RGBA")
        char_dia = char_r * 2
        cropped  = cropped.resize((char_dia, char_dia), Image.LANCZOS)

        # Build canvas with anti-aliased circle mask
        canvas_cx = out_size // 2
        canvas_cy = out_size // 2
        canvas    = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))
        paste_x   = canvas_cx - char_dia // 2
        paste_y   = canvas_cy - char_dia // 2
        canvas.paste(cropped, (paste_x, paste_y))

        # 4× supersampled circle mask
        ss = 4
        mask_large = Image.new("L", (out_size * ss, out_size * ss), 0)
        draw = ImageDraw.Draw(mask_large)
        bcx = canvas_cx * ss
        bcy = canvas_cy * ss
        br  = char_r * ss
        draw.ellipse([bcx - br, bcy - br, bcx + br, bcy + br], fill=255)
        circ_mask = mask_large.resize((out_size, out_size), Image.LANCZOS)
        canvas.putalpha(circ_mask)

        # Composite moldura on top
        if frame is not None:
            canvas = Image.alpha_composite(canvas, frame)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(str(out_path), format="PNG")
        return True, face_meta

    except Exception as exc:
        log.error(f"Token generation error for {img_path.name}: {exc}")
        return False, None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class TokenWorker:
    name = "token"
    kind = "queue"

    def __init__(self, options: dict | None = None) -> None:
        _adopt_legacy_state()
        self._cfg = _load_config(options)

    def pending(self) -> list[WorkItem]:
        global _warned_no_pillow
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            if not _warned_no_pillow:
                make_worker_logger(self.name).warning("Pillow not installed — token generation disabled")
                _warned_no_pillow = True
            return []

        vision_state = _load_vision_state()
        gen_tokens   = _load_gen_tokens()
        queue        = _load_queue()
        all_images   = vision_state.get("images", {})

        items: list[WorkItem] = []

        # Stale index entries whose token file is gone → purge items
        for img_key, entry_data in gen_tokens.items():
            if not (_PROJECT_ROOT / entry_data["tokenPath"]).exists():
                items.append(WorkItem(entry_data.get("sourcePath", img_key),
                                      {"action": "purge", "img_key": img_key}))

        for img_key, entry in all_images.items():
            if entry.get("status") != "ok" or entry.get("isToken", False):
                continue
            src_rel = entry.get("path", "")
            q_entry = queue.get(src_rel, {})
            slot    = (q_entry.get("agents") or {}).get("token")
            reruns  = int((q_entry.get("reruns") or {}).get("token", 0))

            # Poison-pill guard: error slots stay error until reset
            if slot == "error":
                continue

            if entry.get("type") in _SKIP_TYPES:
                if slot == "pending":
                    items.append(WorkItem(src_rel, {"action": "skip-type", "img_key": img_key,
                                                    "entry": entry}))
                continue

            if _is_token_stem(_PROJECT_ROOT / src_rel):
                continue

            if img_key in gen_tokens:
                if slot == "pending":
                    items.append(WorkItem(src_rel, {"action": "reconcile", "img_key": img_key}))
                continue

            if reruns >= _MAX_RERUNS:
                continue
            items.append(WorkItem(src_rel, {"action": "generate", "img_key": img_key,
                                            "entry": entry}))

        return items

    def handle(self, item: WorkItem) -> WorkResult:
        log = make_worker_logger(self.name)
        action  = item.payload.get("action", "generate")
        img_key = item.payload.get("img_key", "")

        if action == "purge":
            gen = _load_gen_tokens()
            entry = gen.pop(img_key, None)
            if entry:
                _save_gen_tokens(gen)
                log.info(f"Purged stale token entry: {entry['tokenPath']}")
            return WorkResult("done", f"purged stale index entry {img_key}")

        if action == "skip-type":
            _set_queue_token_slot(item.key, "skip", log)
            return WorkResult("skip", f"ineligible type: {item.payload['entry'].get('type')}")

        if action == "reconcile":
            _set_queue_token_slot(item.key, "done", log)
            return WorkResult("done", "reconciled existing token slot")

        # generate
        entry    = item.payload["entry"]
        src_rel  = item.key
        img_path = _PROJECT_ROOT / src_rel
        if not img_path.exists():
            return WorkResult("skip", f"source gone: {src_rel}")

        out_path     = img_path.with_name(f"{img_path.stem}-token.png")
        moldura_path = _pick_moldura(entry, self._cfg)

        if out_path.exists():
            ok, face = True, None
            log.info(f"Token already exists: {out_path.name}")
        else:
            ok, face = _make_token(img_path, out_path, self._cfg, log, moldura_path=moldura_path)

        if not ok:
            _set_queue_token_slot(src_rel, "error", log)
            return WorkResult("error", f"token generation failed: {src_rel}")

        gen_tokens = _load_gen_tokens()
        gen_tokens[img_key] = {
            "sourcePath":  src_rel,
            "tokenPath":   out_path.relative_to(_PROJECT_ROOT).as_posix(),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        _save_gen_tokens(gen_tokens)
        _store_face(src_rel, face, log)
        _set_queue_token_slot(src_rel, "done", log)
        log.info(f"Token created: {out_path.name}")
        return WorkResult("done", f"token: {out_path.name}")


def create(options: dict | None = None) -> TokenWorker:
    return TokenWorker(options)


# ---------------------------------------------------------------------------
# Manual single-image entry point (used by the dashboard token editor)
# ---------------------------------------------------------------------------

def run_single(image_path: str, moldura_override: str | None = None,
               image_type: str | None = None) -> int:
    """Generate a token for a single image. Returns 0 on success, 1 on failure."""
    _adopt_legacy_state()
    log = make_worker_logger("token")
    cfg = _load_config()

    img_path = Path(image_path)
    if not img_path.is_absolute():
        img_path = _PROJECT_ROOT / image_path
    if not img_path.exists():
        log.error(f"Image not found: {img_path}")
        return 1
    if _is_token_stem(img_path):
        log.warning(f"Skipping token file as source: {img_path.name}")
        return 1

    # Resolve moldura: explicit override > type-based > default
    if moldura_override:
        moldura_path: Path | None = Path(moldura_override)
    elif image_type:
        entry_stub = {"type": image_type}
        moldura_path = _pick_moldura(entry_stub, cfg)
    else:
        moldura_path = None

    out_path = img_path.parent / (img_path.stem + "-token.png")
    ok, face = _make_token(img_path, out_path, cfg, log, moldura_path=moldura_path)
    if ok:
        gen = _load_gen_tokens()
        rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
        vision_state = _load_vision_state()
        sha_key = vision_state.get("pathIndex", {}).get(rel, "")
        key = sha_key if sha_key and not sha_key.startswith("path:") else f"path:{rel}"
        tok_rel = out_path.relative_to(_PROJECT_ROOT).as_posix()
        gen[key] = {
            "sourcePath": rel,
            "tokenPath": tok_rel,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        _save_gen_tokens(gen)
        _store_face(rel, face, log)
        _set_queue_token_slot(rel, "done", log)
        print(tok_rel, flush=True)
        return 0
    return 1


if __name__ == "__main__":
    import argparse as _argparse
    _parser = _argparse.ArgumentParser()
    _parser.add_argument("--image", help="Single image path to tokenize")
    _parser.add_argument("--moldura", help="Moldura frame path override")
    _parser.add_argument("--type", dest="image_type", help="Image type for moldura selection")
    _args = _parser.parse_args()
    if _args.image:
        raise SystemExit(run_single(_args.image, _args.moldura, _args.image_type))
    worker = create()
    for _item in worker.pending():
        _res = worker.handle(_item)
        print(f"{_res.status} {_item.key}: {_res.detail}")
