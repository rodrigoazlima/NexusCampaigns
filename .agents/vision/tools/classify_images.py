"""vision.tools.06_classify_images

Classifies RPG images in 00-Inbox/images/ via Qwen3-VL.
Writes AGENTS.md-compliant draft entities to 01-Processing/.
No LLM → skip gracefully. Batch: 10 images per run.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    FrontmatterIO,
    LLMClient,
    LLMOfflineError,
    LLMResponseError,
    VisionClassification,
    to_slug,
)
from shared.config import LLMEndpointConfig  # noqa: E402

TASK_ID         = "vision-agent"
SCRIPT_BASENAME = "classify_images.py"
BATCH_SIZE      = 10

_VAULT_ROOT   = _PROJECT_ROOT / "knowledge-base"
_INBOX        = _VAULT_ROOT / "00-Inbox"
_INBOX_IMAGES = _INBOX / "images"
_PROCESSING   = _VAULT_ROOT / "01-Processing"
_AGENT_STATE  = _AGENTS_DIR / "vision" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_SHARED_STATE = _PROJECT_ROOT / ".shared" / "state"
_MASTER_LOG   = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_PROC_IMAGES  = _AGENT_STATE / "processed-images.json"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"
_PROMPT_FILE  = _AGENTS_DIR / "vision" / "prompts" / "classify-image.txt"
_INDEX_MD     = _PROCESSING / "Images Index.md"

_IMAGE_EXTS   = frozenset({".png", ".jpg", ".jpeg", ".webp"})

_LLM_CFG = LLMEndpointConfig(
    url      = "http://localhost:1234/v1/chat/completions",
    model    = "qwen3-vl-4b-instruct",
    type     = "vision",
    provider = "lmstudio",
)


class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"classify-images_{today}.log"
        self._master = _MASTER_LOG

    def _write(self, level: str, msg: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{TASK_ID}] {level}: {msg}"
        print(line, flush=True)
        self._master.parent.mkdir(parents=True, exist_ok=True)
        for p in (self._master, self._daily):
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, m: str)    -> None: self._write("INFO",  m)
    def warning(self, m: str) -> None: self._write("WARN",  m)
    def error(self, m: str)   -> None: self._write("ERROR", m)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, count: int = 0, failed: int = 0) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write("INFO", f"--- DONE --- processed={count} failed={failed} elapsed={elapsed}s")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_token(path: Path) -> bool:
    """Detect transparent-corner PNG = token."""
    if path.suffix.lower() != ".png":
        return False
    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        corners = [
            img.getpixel((0, 0)),
            img.getpixel((w - 1, 0)),
            img.getpixel((0, h - 1)),
            img.getpixel((w - 1, h - 1)),
        ]
        transparent = sum(1 for c in corners if c[3] < 128)
        return transparent >= 3
    except Exception:
        return False


def _load_state() -> dict[str, Any]:
    if not _PROC_IMAGES.exists():
        return {"version": 2, "images": {}, "pathIndex": {}}
    return json.loads(_PROC_IMAGES.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _PROC_IMAGES.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(_PROC_IMAGES)


def _load_queue() -> dict[str, Any]:
    if not _QUEUE_FILE.exists():
        return {}
    return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))


def _save_queue(queue: dict) -> None:
    _SHARED_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
    tmp.replace(_QUEUE_FILE)


def _candidate_images(state: dict, queue: dict) -> list[Path]:
    path_index: set[str] = set(state.get("pathIndex", {}).keys())

    images: list[Path] = []
    for path in sorted(_INBOX_IMAGES.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
            continue
        rel = path.relative_to(_PROJECT_ROOT).as_posix()
        if rel in path_index:
            continue
        queue_entry = queue.get(rel, {})
        agents = queue_entry.get("agents", {})
        if isinstance(agents, dict) and agents.get("vision") == "done":
            continue
        images.append(path)

    # Non-PNG (non-tokens) first; tokens last
    return sorted(images, key=lambda p: (p.suffix.lower() == ".png", p))


def _build_slug(clf: VisionClassification, stem: str) -> str:
    parts = [clf.type.value]
    if clf.ancestry and clf.ancestry != "none":
        parts.append(to_slug(clf.ancestry))
    elif clf.creature_type and clf.creature_type != "none":
        parts.append(to_slug(clf.creature_type))
    if clf.char_class and clf.char_class != "none":
        parts.append(to_slug(clf.char_class))
    if clf.environment and clf.environment.value != "none":
        parts.append(clf.environment.value)
    parts.append(to_slug(stem)[:20])
    return "-".join(parts)


def _unique_output_path(slug: str) -> Path:
    _PROCESSING.mkdir(parents=True, exist_ok=True)
    candidate = _PROCESSING / f"{slug}.md"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = _PROCESSING / f"{slug}-{counter:02d}.md"
        if not candidate.exists():
            return candidate
        counter += 1


def _write_draft(path: Path, clf: VisionClassification, image_path: Path) -> None:
    today = date.today().isoformat()
    slug  = path.stem
    rel_img = image_path.relative_to(_PROJECT_ROOT).as_posix()
    tags  = [clf.type.value]
    if clf.ancestry and clf.ancestry != "none":
        tags.append(clf.ancestry)
    if clf.creature_type and clf.creature_type != "none":
        tags.append(clf.creature_type)
    if clf.element and clf.element.value != "none":
        tags.append(clf.element.value)

    frontmatter = {
        "id":            slug,
        "type":          "npc" if clf.type.value in ("portrait", "body", "token") else "location",
        "status":        "draft",
        "quality":       0,
        "created":       today,
        "updated":       today,
        "tags":          tags,
        "source":        [rel_img],
        "reviewed":      False,
        "relationships": [],
    }

    body = (
        f"\n## Description\n\n{clf.description}\n\n"
        f"## Details\n\n"
        f"- **Ancestry**: {clf.ancestry}\n"
        f"- **Class**: {clf.char_class}\n"
        f"- **Creature type**: {clf.creature_type}\n"
        f"- **Element**: {clf.element.value}\n"
        f"- **Environment**: {clf.environment.value}\n\n"
        f"## Related\n\n"
    )

    fio = FrontmatterIO()
    fio.write(path, frontmatter, body)


def _append_index(image_path: Path, clf: VisionClassification, slug: str) -> None:
    _INDEX_MD.parent.mkdir(parents=True, exist_ok=True)
    today  = date.today().isoformat()
    rel    = image_path.relative_to(_PROJECT_ROOT).as_posix()
    row    = f"| {today} | [[{slug}]] | {clf.type.value} | {clf.ancestry} | {clf.element.value} | `{rel}` |\n"
    if not _INDEX_MD.exists():
        _INDEX_MD.write_text(
            "# Images Index\n\n"
            "| Date | Entity | Type | Ancestry | Element | Source |\n"
            "|------|--------|------|----------|---------|--------|\n",
            encoding="utf-8",
        )
    with open(_INDEX_MD, "a", encoding="utf-8") as fh:
        fh.write(row)


def main() -> None:
    log = _Logger()
    t0  = log.start()

    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    _PROCESSING.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("Qwen3-VL (localhost:1234) offline — skipping batch")
        log.done(t0)
        sys.exit(0)

    prompt = _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists() else ""

    state = _load_state()
    queue = _load_queue()
    candidates = _candidate_images(state, queue)

    if not candidates:
        log.info("No unprocessed images found")
        log.done(t0)
        sys.exit(0)

    batch   = candidates[:BATCH_SIZE]
    count   = 0
    failed  = 0
    log.info(f"Batch: {len(batch)} of {len(candidates)} image(s)")

    for img_path in batch:
        rel   = img_path.relative_to(_PROJECT_ROOT).as_posix()
        sha   = _sha256(img_path)
        is_tk = _is_token(img_path)

        try:
            raw = client.vision_chat(
                img_path,
                prompt or "Classify this RPG image. Return JSON only.",
                system="You are a Pathfinder 2e image classifier. Return ONLY valid JSON.",
                max_tokens=300,
            )
            clf = VisionClassification.model_validate(raw)
            if is_tk:
                from shared.models import ImageType
                clf = clf.model_copy(update={"type": ImageType.token})

        except LLMOfflineError:
            log.warning(f"LLM offline while processing {img_path.name} — aborting batch")
            break
        except (LLMResponseError, Exception) as exc:
            log.error(f"Classification failed for {img_path.name}: {exc}")
            failed += 1
            continue

        slug     = _build_slug(clf, img_path.stem)
        out_path = _unique_output_path(slug)
        _write_draft(out_path, clf, img_path)
        _append_index(img_path, clf, out_path.stem)
        log.info(f"Classified: {img_path.name} → {out_path.name} ({clf.type.value})")

        # Persist after each image
        img_key = sha
        state["images"][img_key] = {
            "path":         rel,
            "processedAt":  datetime.now(timezone.utc).isoformat(),
            "originalName": img_path.name,
            "type":         clf.type.value,
            "ancestry":     clf.ancestry,
            "class":        clf.char_class,
            "creature_type": clf.creature_type,
            "element":      clf.element.value,
            "environment":  clf.environment.value,
            "description":  clf.description,
            "sha256":       sha,
            "isToken":      is_tk,
            "status":       "ok",
        }
        state["pathIndex"][rel] = img_key
        _save_state(state)

        if rel in queue and isinstance(queue[rel].get("agents"), dict):
            queue[rel]["agents"]["vision"] = "done"
            _save_queue(queue)

        count += 1

    log.done(t0, count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "list_pending_images",
        "description": "Return JSON list of image paths in 00-Inbox/images/ not yet classified.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "detect_token",
        "description": "Check whether a PNG image is a circular token (transparent corner/edge pixels).",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Absolute path to the PNG image"},
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "classify_image",
        "description": "Classify a single image via the local vision LLM (type, ancestry, class, element, environment). Returns JSON classification.",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Absolute path to the image file"},
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "run_batch",
        "description": "Classify up to BATCH_SIZE pending images and write drafts to 01-Processing/. Returns count processed.",
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

    if name == "list_pending_images":
        state = _load_state()
        queue = _load_queue()
        candidates = _candidate_images(state, queue)
        return _json.dumps([str(p) for p in candidates[:20]])

    if name == "detect_token":
        p = Path(args["image_path"])
        return _json.dumps({"is_token": _is_token(p), "path": str(p)})

    if name == "classify_image":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Classification run complete"

    if name == "run_batch":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")
