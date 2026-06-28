"""token.tools.generate_tokens

Generates 512×512 circular portrait tokens from classified character images.
Face detection: MediaPipe → OpenCV Haar → upper-center crop fallback.
Moldura: inner radius auto-detected from frame alpha channel.
Moldura selection: per-type override from agent config (moldura_by_type).
No LLM. Batch: 10 per run.

New logic (2026-06):
  - Purges stale generated-tokens.json entries where tokenPath no longer exists
  - Skips source images whose stem ends in -token or contains .token (defense-in-depth)
  - Updates inbox-queue.json token slot: done after generation, skip for ineligible types

New logic (2026-06-28):
  - detect_ring_radii: auto-detect moldura inner radius from alpha channel
  - Face crop scaled to fill inner circle (not fixed pixel padding)
  - padding as fraction of inner diameter (0.0–0.49)
  - focus_head accepts array [top, right, bottom, left] or legacy dict
  - moldura_by_type in config: pick frame by image type from vision state
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared.logger import Logger, _ensure_utf8_stdout  # noqa: E402
from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

TASK_ID         = "token-agent"
SCRIPT_BASENAME = "generate_tokens.py"
BATCH_SIZE      = 10

_VAULT_ROOT   = _PROJECT_ROOT / "knowledge-base"
_INBOX_IMAGES = _VAULT_ROOT / "00-Inbox" / "images"
_AGENT_STATE  = _AGENTS_DIR / "token" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_MASTER_LOG   = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_VISION_STATE = _AGENTS_DIR / "vision" / "state" / "processed-images.json"
_GEN_TOKENS   = _AGENT_STATE / "generated-tokens.json"
_CONFIG_FILE  = _AGENT_STATE / "10-generate-tokens.json"  # legacy fallback
_AGENT_JSON   = _AGENTS_DIR / "token" / "agent.json"
_QUEUE_FILE   = _PROJECT_ROOT / ".system" / "state" / "inbox-queue.json"

_DEFAULT_CFG: dict[str, Any] = {
    "size":           512,
    "padding":        0.18,       # fraction of inner circle diameter (0–0.49)
    "forehead_ratio": 0.35,       # extra head room above face bbox top
    "body_ratio":     0.30,       # extra body room below face bbox bottom
    "focus_head":     [0, 0, 0, 0],  # [top, right, bottom, left] % of crop_size
    "moldura_path":   "knowledge-base/00-Inbox/tokens/Molduras/moldura_default.png",
    "moldura_by_type": {},        # e.g. {"creature": "path/to/creature_frame.png"}
}

_SKIP_TYPES = frozenset({"battlemap", "scene"})

_MODULE_FILE = Path(__file__)


def _is_token_stem(p: Path) -> bool:
    stem = p.stem
    return stem.endswith("-token") or ".token" in stem


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


def _load_config() -> dict[str, Any]:
    # Primary: read token_config from agent.json (edited via dashboard config dialog)
    if _AGENT_JSON.exists():
        try:
            agent = json.loads(_AGENT_JSON.read_text(encoding="utf-8"))
            if "token_config" in agent:
                cfg = dict(_DEFAULT_CFG)
                cfg.update(agent["token_config"])
                return cfg
        except Exception:
            pass
    # Fallback: legacy state config file
    if not _CONFIG_FILE.exists():
        _AGENT_STATE.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(_DEFAULT_CFG, indent=2), encoding="utf-8")
        return dict(_DEFAULT_CFG)
    stored = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    cfg = dict(_DEFAULT_CFG)
    cfg.update(stored)
    return cfg


def _load_vision_state() -> dict[str, Any]:
    if not _VISION_STATE.exists():
        return {"images": {}, "pathIndex": {}}
    return json.loads(_VISION_STATE.read_text(encoding="utf-8"))


def _load_gen_tokens() -> dict[str, Any]:
    if not _GEN_TOKENS.exists():
        return {}
    return json.loads(_GEN_TOKENS.read_text(encoding="utf-8"))


def _save_gen_tokens(data: dict) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _GEN_TOKENS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(_GEN_TOKENS)


def _purge_stale_gen_tokens(log: Logger) -> int:
    gen = _load_gen_tokens()
    stale = [k for k, v in gen.items() if not (_PROJECT_ROOT / v["tokenPath"]).exists()]
    if stale:
        for k in stale:
            log.info(f"Purging stale token entry: {gen[k]['tokenPath']}")
            del gen[k]
        _save_gen_tokens(gen)
    return len(stale)


def _load_queue() -> dict[str, Any]:
    if not _QUEUE_FILE.exists():
        return {}
    return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))


def _save_queue(queue: dict[str, Any]) -> None:
    tmp = _QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
    tmp.replace(_QUEUE_FILE)


def _set_queue_token_slot(source_rel: str, status: str, log: Logger) -> bool:
    queue = _load_queue()
    if source_rel not in queue:
        return False
    entry = queue[source_rel]
    agents = entry.get("agents", {})
    if agents.get("token") == status:
        return False
    agents["token"] = status
    entry["agents"] = agents
    queue[source_rel] = entry
    _save_queue(queue)
    log.info(f"Queue token slot [{status}]: {source_rel.split('/')[-1]}")
    return True


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

def _detect_face_mediapipe(img_array: Any) -> tuple[int, int, int, int] | None:
    try:
        import mediapipe as mp  # type: ignore[import]
        solutions = getattr(mp, "solutions", None)
        if not (solutions and hasattr(solutions, "face_detection")):
            return None
        mp_face = solutions.face_detection
        with mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.3) as det:
            rgb = img_array[:, :, ::-1].copy() if img_array.shape[2] == 3 else img_array
            res = det.process(rgb)
            if not res.detections:
                return None
            best = max(res.detections, key=lambda d: d.score[0])
            bb = best.location_data.relative_bounding_box
            h, w = img_array.shape[:2]
            fw = int(bb.width  * w)
            fh = int(bb.height * h)
            cx = int(bb.xmin * w) + fw // 2
            cy = int(bb.ymin * h) + fh // 2
            return cx, cy, fw, fh
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
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
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
                moldura_path: Path | None = None) -> bool:
    try:
        from PIL import Image, ImageDraw
        import numpy as np
    except ImportError:
        log.error("Pillow not installed — cannot generate tokens")
        return False

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

        # Detect face (center-point form)
        face = _detect_face_mediapipe(arr) or _detect_face_opencv(arr)

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
        return True

    except Exception as exc:
        log.error(f"Token generation error for {img_path.name}: {exc}")
        return False


def main() -> None:
    _ensure_utf8_stdout()
    log = _make_logger()
    t0  = log.start()
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        log.error("Pillow not installed — install: pip install Pillow")
        log.done(t0, key="generated", count=0, failed=0)
        sys.exit(1)

    purged = _purge_stale_gen_tokens(log)
    if purged:
        log.info(f"Purged {purged} stale token index entries")

    cfg          = _load_config()
    vision_state = _load_vision_state()
    gen_tokens   = _load_gen_tokens()

    all_images = vision_state.get("images", {})

    # Mark skip-type images in queue
    for img_key, entry in all_images.items():
        if entry.get("status") == "ok" and not entry.get("isToken", False):
            if entry.get("type") in _SKIP_TYPES:
                _set_queue_token_slot(entry["path"], "skip", log)

    # Reconcile queue slots for already-generated tokens
    reconciled = 0
    for entry_data in gen_tokens.values():
        src_rel = entry_data.get("sourcePath", "")
        if src_rel and _set_queue_token_slot(src_rel, "done", log):
            reconciled += 1
    if reconciled:
        log.info(f"Reconciled {reconciled} existing token queue slots")

    eligible = [
        (img_key, entry)
        for img_key, entry in all_images.items()
        if entry.get("status") == "ok"
        if not entry.get("isToken", False)
        if entry.get("type") not in _SKIP_TYPES
        if img_key not in gen_tokens
        if not _is_token_stem(_PROJECT_ROOT / entry["path"])
    ]

    if not eligible:
        log.info("No eligible images for token generation")
        log.done(t0, key="generated", count=0, failed=0)
        sys.exit(0)

    batch  = eligible[:BATCH_SIZE]
    count  = 0
    failed = 0
    log.info(f"Batch: {len(batch)} of {len(eligible)} image(s)")

    for img_key, entry in batch:
        src_rel  = entry["path"]
        img_path = _PROJECT_ROOT / src_rel
        if not img_path.exists():
            log.warning(f"Source gone: {src_rel}")
            failed += 1
            continue

        out_path    = img_path.with_name(f"{img_path.stem}-token.png")
        moldura_path = _pick_moldura(entry, cfg)

        if out_path.exists():
            log.info(f"Token already exists: {out_path.name}")
            out_rel = out_path.relative_to(_PROJECT_ROOT).as_posix()
            gen_tokens[img_key] = {
                "sourcePath":  src_rel,
                "tokenPath":   out_rel,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
            _save_gen_tokens(gen_tokens)
            _set_queue_token_slot(src_rel, "done", log)
            count += 1
            continue

        ok = _make_token(img_path, out_path, cfg, log, moldura_path=moldura_path)
        if ok:
            out_rel = out_path.relative_to(_PROJECT_ROOT).as_posix()
            gen_tokens[img_key] = {
                "sourcePath":  src_rel,
                "tokenPath":   out_rel,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
            _save_gen_tokens(gen_tokens)
            _set_queue_token_slot(src_rel, "done", log)
            log.info(f"Token created: {out_path.name}")
            count += 1
        else:
            failed += 1

    log.done(t0, key="generated", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


def run_single(image_path: str, moldura_override: str | None = None,
               image_type: str | None = None) -> int:
    """Generate a token for a single image. Returns 0 on success, 1 on failure."""
    _ensure_utf8_stdout()
    log = _make_logger()
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
    ok = _make_token(img_path, out_path, cfg, log, moldura_path=moldura_path)
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
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "list_pending_portraits",
        "description": "Return JSON list of portrait/body image paths not yet tokenized.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "generate_token",
        "description": (
            "Generate a circular 512×512 portrait token from a source image. "
            "Detects face and centers crop on it. Scales to fill moldura inner circle. "
            "Optional: pass image_type to select per-type moldura from config."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Absolute or project-relative path to source image"},
                "image_type": {"type": "string", "description": "Vision type (npc, creature, body…) for moldura selection"},
                "moldura_override": {"type": "string", "description": "Explicit moldura PNG path, overrides config"},
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "run_batch",
        "description": "Generate tokens for up to BATCH_SIZE pending portrait images. Returns count generated.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import io, contextlib, json as _json
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    if name == "list_pending_portraits":
        vision_state = _load_vision_state()
        gen_tokens = _load_gen_tokens()
        images = vision_state.get("images", {})
        pending = [
            entry.get("path", "")
            for img_key, entry in images.items()
            if entry.get("status") == "ok"
            and not entry.get("isToken", False)
            and entry.get("type") not in _SKIP_TYPES
            and img_key not in gen_tokens
        ]
        return _json.dumps(pending[:20])

    if name == "generate_token":
        cfg = _load_config()
        log = _make_logger()
        img_path = Path(args["image_path"])
        if not img_path.exists():
            img_path = _PROJECT_ROOT / args["image_path"]

        moldura_path: Path | None = None
        if args.get("moldura_override"):
            moldura_path = Path(args["moldura_override"])
        elif args.get("image_type"):
            moldura_path = _pick_moldura({"type": args["image_type"]}, cfg)

        out_path = img_path.parent / (img_path.stem + "-token.png")
        ok = _make_token(img_path, out_path, cfg, log, moldura_path=moldura_path)
        if ok:
            gen = _load_gen_tokens()
            rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
            vision_state = _load_vision_state()
            sha_key = vision_state.get("pathIndex", {}).get(rel, "")
            key = sha_key if sha_key and not sha_key.startswith("path:") else f"path:{rel}"
            gen[key] = {
                "sourcePath":  rel,
                "tokenPath":   out_path.relative_to(_PROJECT_ROOT).as_posix(),
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
            _save_gen_tokens(gen)
            _set_queue_token_slot(rel, "done", log)
            return f"Token generated: {out_path.name}"
        return f"Token generation failed for: {img_path.name}"

    if name == "run_batch":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Token batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")
