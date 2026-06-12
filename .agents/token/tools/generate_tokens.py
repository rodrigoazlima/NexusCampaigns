"""token.tools.generate_tokens

Generates 512×512 circular portrait tokens from classified character images.
Face detection: MediaPipe → OpenCV Haar → upper-center crop fallback.
No LLM. Batch: 10 per run.
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
_CONFIG_FILE  = _AGENT_STATE / "10-generate-tokens.json"

_DEFAULT_CFG: dict[str, Any] = {
    "size":           512,
    "padding":        10,
    "forehead_ratio": 0.15,
    "body_ratio":     0.55,
    "focus_head": {"top": 0, "right": 0, "bottom": 0, "left": 0},
    "moldura_path":   "knowledge-base/00-Inbox/tokens/Molduras/moldura_default.png",
}

_SKIP_TYPES = frozenset({"battlemap", "scene"})

_MODULE_FILE = Path(__file__)


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


def _load_config() -> dict[str, Any]:
    if not _CONFIG_FILE.exists():
        _AGENT_STATE.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(_DEFAULT_CFG, indent=2), encoding="utf-8")
        return dict(_DEFAULT_CFG)
    return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))


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


# ---------------------------------------------------------------------------
# Face detection
# ---------------------------------------------------------------------------

def _detect_face_mediapipe(img_array: Any) -> tuple[int, int, int, int] | None:
    try:
        import mediapipe as mp  # type: ignore[import]
        import numpy as np

        mp_face = mp.solutions.face_detection
        with mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.5) as det:
            rgb = img_array[:, :, ::-1].copy() if img_array.shape[2] == 3 else img_array
            res = det.process(rgb)
            if not res.detections:
                return None
            best = res.detections[0].location_data.relative_bounding_box
            h, w = img_array.shape[:2]
            x = int(best.xmin * w)
            y = int(best.ymin * h)
            bw = int(best.width * w)
            bh = int(best.height * h)
            return x, y, bw, bh
    except Exception:
        return None


def _detect_face_opencv(img_array: Any) -> tuple[int, int, int, int] | None:
    try:
        import cv2  # type: ignore[import]
        import numpy as np
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        cascade_path = str(
            Path(__file__).parent / "haarcascade_frontalface_default.xml"
        )
        if not Path(cascade_path).exists():
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        clf = cv2.CascadeClassifier(cascade_path)
        faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if not len(faces):
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return int(x), int(y), int(w), int(h)
    except Exception:
        return None


def _upper_center_crop(w: int, h: int, cfg: dict) -> tuple[int, int, int, int]:
    size = min(w, h) // 2
    x = (w - size) // 2
    y = int(h * 0.05)
    return x, y, size, size


def _apply_focus_offset(x: int, y: int, bw: int, bh: int, cfg: dict) -> tuple[int, int, int, int]:
    focus = cfg.get("focus_head", {})
    dx = int(bw * focus.get("left", 0) / 100) - int(bw * focus.get("right", 0) / 100)
    dy = int(bh * focus.get("top", 0) / 100) - int(bh * focus.get("bottom", 0) / 100)
    return x + dx, y + dy, bw, bh


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

def _make_token(img_path: Path, out_path: Path, cfg: dict, log: Logger) -> bool:
    try:
        from PIL import Image, ImageDraw
        import numpy as np
    except ImportError:
        log.error("Pillow not installed — cannot generate tokens")
        return False

    try:
        img   = Image.open(img_path).convert("RGBA")
        w, h  = img.size
        arr   = np.array(img.convert("RGB"))

        face = (
            _detect_face_mediapipe(arr)
            or _detect_face_opencv(arr)
        )

        if face:
            fx, fy, fw, fh = face
            fx, fy, fw, fh = _apply_focus_offset(fx, fy, fw, fh, cfg)
            forehead  = int(fh * cfg.get("forehead_ratio", 0.15))
            body_ext  = int(fh * cfg.get("body_ratio", 0.55))
            crop_y    = max(0, fy - forehead)
            crop_h    = fh + forehead + body_ext
            crop_size = max(fw, crop_h)
            crop_x    = max(0, fx + fw // 2 - crop_size // 2)
        else:
            crop_x, crop_y, crop_size, _ = _upper_center_crop(w, h, cfg)

        crop_x2 = min(w, crop_x + crop_size)
        crop_y2 = min(h, crop_y + crop_size)
        crop    = img.crop((crop_x, crop_y, crop_x2, crop_y2))

        size    = cfg.get("size", 512)
        padding = cfg.get("padding", 10)
        inner   = size - 2 * padding

        # 4× supersampled circle mask
        ss = 4
        mask_large = Image.new("L", (inner * ss, inner * ss), 0)
        draw = ImageDraw.Draw(mask_large)
        draw.ellipse((0, 0, inner * ss - 1, inner * ss - 1), fill=255)
        mask = mask_large.resize((inner, inner), Image.LANCZOS)

        char = crop.resize((inner, inner), Image.LANCZOS).convert("RGBA")
        char.putalpha(mask)

        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(char, (padding, padding), char)

        moldura_rel = cfg.get("moldura_path", "")
        if moldura_rel:
            moldura_path = _PROJECT_ROOT / moldura_rel
            if moldura_path.exists():
                moldura = Image.open(moldura_path).convert("RGBA").resize((size, size), Image.LANCZOS)
                canvas  = Image.alpha_composite(canvas, moldura)

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

    cfg          = _load_config()
    vision_state = _load_vision_state()
    gen_tokens   = _load_gen_tokens()

    eligible = [
        (img_key, entry)
        for img_key, entry in vision_state.get("images", {}).items()
        if entry.get("status") == "ok"
        if not entry.get("isToken", False)
        if entry.get("type") not in _SKIP_TYPES
        if img_key not in gen_tokens
    ]

    if not eligible:
        log.info("No eligible images for token generation")
        log.done(t0, key="generated", count=0, failed=0)
        sys.exit(0)

    batch   = eligible[:BATCH_SIZE]
    count   = 0
    failed  = 0
    log.info(f"Batch: {len(batch)} of {len(eligible)} image(s)")

    for img_key, entry in batch:
        img_path = _PROJECT_ROOT / entry["path"]
        if not img_path.exists():
            log.warning(f"Source gone: {entry['path']}")
            failed += 1
            continue

        out_path = img_path.with_name(f"{img_path.stem}-token.png")
        if out_path.exists():
            log.info(f"Token already exists: {out_path.name}")
            gen_tokens[img_key] = {
                "sourcePath":  entry["path"],
                "tokenPath":   out_path.relative_to(_PROJECT_ROOT).as_posix(),
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
            _save_gen_tokens(gen_tokens)
            count += 1
            continue

        ok = _make_token(img_path, out_path, cfg, log)
        if ok:
            out_rel = out_path.relative_to(_PROJECT_ROOT).as_posix()
            gen_tokens[img_key] = {
                "sourcePath":  entry["path"],
                "tokenPath":   out_rel,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
            _save_gen_tokens(gen_tokens)
            log.info(f"Token created: {out_path.name}")
            count += 1
        else:
            failed += 1

    log.done(t0, key="generated", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
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
        "description": "Generate a circular 512×512 portrait token from a source image. Detects face, applies circular mask, composites moldura frame.",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Absolute path to the source portrait/body image"},
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
        out_path = img_path.parent / (img_path.stem + "-token.png")
        ok = _make_token(img_path, out_path, cfg, log)
        if ok:
            gen = _load_gen_tokens()
            rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
            # resolve SHA256 key from vision state pathIndex
            vision_state = _load_vision_state()
            sha_key = vision_state.get("pathIndex", {}).get(rel, "")
            key = sha_key if sha_key and not sha_key.startswith("path:") else f"path:{rel}"
            gen[key] = {
                "sourcePath":  rel,
                "tokenPath":   out_path.relative_to(_PROJECT_ROOT).as_posix(),
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            }
            _save_gen_tokens(gen)
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
