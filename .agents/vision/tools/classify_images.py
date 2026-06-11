"""vision.tools.classify_images

Classifies RPG images in 00-Inbox/images/ via Qwen3-VL.
Renames images to canonical slug format in-place.
Writes AGENTS.md-compliant draft entities to 01-Processing/.
No LLM available → skip gracefully (no images marked failed). Batch: 10 per run.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    FrontmatterIO,
    LLMClient,
    Logger,
    LLMOfflineError,
    LLMResponseError,
    SignalEmitter,
    VisionClassification,
    to_slug,
)
from shared.config import LLMEndpointConfig  # noqa: E402
from shared.models import Element, Environment, ImageType  # noqa: E402

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
_TOKEN_LINKS  = _AGENT_STATE / "token-links.json"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"
_PROMPT_FILE  = _AGENTS_DIR / "vision" / "prompts" / "classify-image.txt"
_INDEX_MD     = _PROCESSING / "Images Index.md"
_SIGNALS_DIR  = _AGENTS_DIR / "runtime" / "state" / "signals"

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})

# Types excluded from face-match candidate pool
_EXCLUDE_TYPES = frozenset({"token", "battlemap", "scene"})

_FACE_SIMILARITY_THRESHOLD = 0.85  # cosine similarity for face-region match

_LLM_CFG = LLMEndpointConfig(
    url      = "http://localhost:1234/v1/chat/completions",
    model    = "qwen3-vl-4b-instruct",
    type     = "vision",
    provider = "lmstudio",
)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Token detection
# ---------------------------------------------------------------------------

def _is_token(path: Path) -> bool:
    """Return True if PNG has ≥2 transparent corners — canonical token detection."""
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
        return sum(1 for c in corners if c[3] < 128) >= 2
    except Exception:
        return False


# ---------------------------------------------------------------------------
# State I/O  (atomic writes per G8)
# ---------------------------------------------------------------------------

def _load_state() -> dict[str, Any]:
    if not _PROC_IMAGES.exists():
        return {"version": 2, "images": {}, "pathIndex": {}}
    return json.loads(_PROC_IMAGES.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _PROC_IMAGES.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(_PROC_IMAGES)


def _load_token_links() -> dict[str, Any]:
    if not _TOKEN_LINKS.exists():
        return {}
    return json.loads(_TOKEN_LINKS.read_text(encoding="utf-8"))


def _save_token_links(links: dict) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _TOKEN_LINKS.with_suffix(".tmp")
    tmp.write_text(json.dumps(links, indent=2, default=str), encoding="utf-8")
    tmp.replace(_TOKEN_LINKS)


def _load_queue() -> dict[str, Any]:
    if not _QUEUE_FILE.exists():
        return {}
    return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))


def _save_queue(queue: dict) -> None:
    _SHARED_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
    tmp.replace(_QUEUE_FILE)


# ---------------------------------------------------------------------------
# Candidate discovery
# ---------------------------------------------------------------------------

def _candidate_images(state: dict, queue: dict) -> list[Path]:
    """Return unprocessed images, non-PNG first (tokens last per spec)."""
    path_index: set[str] = set(state.get("pathIndex", {}).keys())
    images: list[Path] = []
    for path in sorted(_INBOX_IMAGES.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
            continue
        rel = path.relative_to(_PROJECT_ROOT).as_posix()
        if rel in path_index:
            continue
        agents = queue.get(rel, {}).get("agents", {})
        if isinstance(agents, dict) and agents.get("vision") == "done":
            continue
        images.append(path)
    return sorted(images, key=lambda p: (p.suffix.lower() == ".png", p))


# ---------------------------------------------------------------------------
# Token face matching
# ---------------------------------------------------------------------------

def _get_folder_candidates(folder: Path, state: dict) -> list[Path]:
    """Return processed non-token, non-battlemap image paths in the same folder.

    Only returns images with a successful state entry (status != failed).
    Used to build the candidate pool for token face matching.
    """
    path_index = state.get("pathIndex", {})
    images     = state.get("images", {})
    candidates: list[Path] = []

    for rel_str, sha_or_key in path_index.items():
        if sha_or_key.startswith("path:"):
            continue  # failed image
        path = _PROJECT_ROOT / rel_str
        if path.parent != folder:
            continue
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        entry = images.get(sha_or_key)
        if not entry or not isinstance(entry, dict):
            continue
        if entry.get("status") == "failed":
            continue
        if entry.get("type") in _EXCLUDE_TYPES:
            continue
        if path.exists():
            candidates.append(path)

    return candidates


def _try_face_match(token_path: Path, candidates: list[Path]) -> Optional[Path]:
    """Match a token to its source portrait via center-crop pixel similarity.

    Uses PIL + numpy only — no heavy dependencies. Falls back to None if
    either dep is missing or any image fails to load.
    Returns the best match above _FACE_SIMILARITY_THRESHOLD, or None.
    """
    if not candidates:
        return None

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    def _face_vector(path: Path) -> Optional[Any]:
        try:
            img = Image.open(path).convert("L")
            w, h = img.size
            # Heuristic face region: horizontal center 40%, vertical upper 50%
            x0, x1 = int(w * 0.3), int(w * 0.7)
            y0, y1 = int(h * 0.1), int(h * 0.6)
            crop = img.crop((x0, y0, x1, y1)).resize((32, 32))
            vec  = np.array(crop, dtype=np.float32).flatten()
            norm = np.linalg.norm(vec)
            return vec / norm if norm > 0 else None
        except Exception:
            return None

    token_vec = _face_vector(token_path)
    if token_vec is None:
        return None

    best_path:  Optional[Path] = None
    best_score: float          = 0.0

    for cand in candidates:
        cand_vec = _face_vector(cand)
        if cand_vec is None:
            continue
        score = float((token_vec * cand_vec).sum())  # cosine sim (vecs are unit-norm)
        if score > best_score:
            best_score = score
            best_path  = cand

    return best_path if best_score >= _FACE_SIMILARITY_THRESHOLD else None


def _inherit_clf_from_state(entry: dict) -> VisionClassification:
    """Rebuild a VisionClassification from a processed-images.json entry.

    Overrides type to `token` — the token inherits all other metadata from
    its matched source portrait.
    """
    return VisionClassification(
        type          = ImageType.token,
        ancestry      = entry.get("ancestry", "none"),
        **{"class": entry.get("class", "none")},
        creature_type = entry.get("creature_type", "none"),
        element       = Element(entry.get("element",      "none")),
        environment   = Environment(entry.get("environment", "none")),
        description   = entry.get("description", ""),
    )


# ---------------------------------------------------------------------------
# Slug builders
# ---------------------------------------------------------------------------

def _image_filename_slug(clf: VisionClassification) -> str:
    """Canonical image filename slug per agent-vision.spec.md.

    portrait / body / token : {ancestry}-{class}-{element}.{type}
    battlemap / scene       : {type}-{environment}
    """
    t = clf.type.value
    if t in ("portrait", "body", "token"):
        parts: list[str] = []
        if clf.ancestry and clf.ancestry != "none":
            parts.append(to_slug(clf.ancestry))
        elif clf.creature_type and clf.creature_type != "none":
            parts.append(to_slug(clf.creature_type))
        if clf.char_class and clf.char_class != "none":
            parts.append(to_slug(clf.char_class))
        if clf.element and clf.element.value != "none":
            parts.append(clf.element.value)
        return ("-".join(parts) if parts else "unknown") + f".{t}"
    else:
        env = clf.environment.value if clf.environment.value != "none" else "unknown"
        return f"{t}-{env}"


def _entity_slug(clf: VisionClassification) -> str:
    """Entity slug for the MD file per data-contracts.spec.md: {type}-{descriptors}."""
    t = clf.type.value
    parts = [t]
    if t in ("portrait", "body", "token"):
        if clf.ancestry and clf.ancestry != "none":
            parts.append(to_slug(clf.ancestry))
        elif clf.creature_type and clf.creature_type != "none":
            parts.append(to_slug(clf.creature_type))
        if clf.char_class and clf.char_class != "none":
            parts.append(to_slug(clf.char_class))
        if clf.element and clf.element.value != "none":
            parts.append(clf.element.value)
    else:
        if clf.environment and clf.environment.value != "none":
            parts.append(clf.environment.value)
    return "-".join(parts)


def _resolve_image_target(src: Path, img_slug: str) -> Path:
    """Resolve target path for in-place image rename. Bumps filename on collision."""
    ext    = src.suffix.lower()
    target = src.parent / f"{img_slug}{ext}"
    if not target.exists() or target == src:
        return target
    counter = 1
    while True:
        target = src.parent / f"{img_slug}-{counter:02d}{ext}"
        if not target.exists():
            return target
        counter += 1


def _resolve_entity_path(slug: str) -> Path:
    """Resolve output MD path in 01-Processing/. Bumps on collision."""
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


# ---------------------------------------------------------------------------
# Image rename
# ---------------------------------------------------------------------------

def _rename_image(src: Path, clf: VisionClassification) -> Path:
    """Rename image to canonical slug format in-place. Returns new path."""
    img_slug = _image_filename_slug(clf)
    target   = _resolve_image_target(src, img_slug)
    if target != src:
        src.rename(target)
    return target


# ---------------------------------------------------------------------------
# Draft writing
# ---------------------------------------------------------------------------

def _write_draft(
    path: Path,
    clf: VisionClassification,
    image_path: Path,
    sha256: Optional[str] = None,
) -> None:
    today   = date.today().isoformat()
    slug    = path.stem
    rel_img = image_path.relative_to(_PROJECT_ROOT).as_posix()

    tags: list[str] = [clf.type.value]
    if clf.ancestry and clf.ancestry != "none":
        tags.append(clf.ancestry)
    if clf.creature_type and clf.creature_type != "none":
        tags.append(clf.creature_type)
    if clf.element and clf.element.value != "none":
        tags.append(clf.element.value)

    frontmatter: dict[str, Any] = {
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
    if sha256:
        frontmatter["sha256"] = sha256

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

    FrontmatterIO().write(path, frontmatter, body)


# ---------------------------------------------------------------------------
# Images Index
# ---------------------------------------------------------------------------

def _append_index(
    image_path: Path,
    clf: VisionClassification,
    entity_slug: str,
) -> None:
    _INDEX_MD.parent.mkdir(parents=True, exist_ok=True)
    today    = date.today().isoformat()
    rel      = image_path.relative_to(_PROJECT_ROOT).as_posix()
    ancestry = clf.ancestry if clf.ancestry != "none" else clf.creature_type
    row = (
        f"| {today} | [[{entity_slug}]] | {clf.type.value} "
        f"| {ancestry} | {clf.element.value} | `{rel}` |\n"
    )
    if not _INDEX_MD.exists():
        _INDEX_MD.write_text(
            "# Images Index\n\n"
            "| Date | Entity | Type | Ancestry | Element | Source |\n"
            "|------|--------|------|----------|---------|--------|\n",
            encoding="utf-8",
        )
    with open(_INDEX_MD, "a", encoding="utf-8") as fh:
        fh.write(row)


# ---------------------------------------------------------------------------
# Single-image classification
# ---------------------------------------------------------------------------

def _classify_one(
    img_path: Path,
    client: LLMClient,
    prompt: str,
    is_tk: bool,
) -> VisionClassification:
    """Classify one image via LLM. Raises LLMOfflineError / LLMResponseError."""
    raw = client.vision_chat(
        img_path,
        prompt or "Classify this RPG image. Return JSON only.",
        system="You are a Pathfinder 2e image classifier. Return ONLY valid JSON.",
        max_tokens=350,
    )
    clf = VisionClassification.model_validate(raw)
    if is_tk:
        clf = clf.model_copy(update={"type": ImageType.token})
    return clf


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log = Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )
    t0 = log.start()

    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    _PROCESSING.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("Qwen3-VL (localhost:1234) offline — skipping batch")
        log.done(t0, key="classified", count=0, failed=0)
        sys.exit(0)

    prompt      = _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists() else ""
    state       = _load_state()
    token_links = _load_token_links()
    queue       = _load_queue()
    candidates  = _candidate_images(state, queue)

    if not candidates:
        log.info("No unprocessed images found")
        log.done(t0, key="classified", count=0, failed=0)
        sys.exit(0)

    batch   = candidates[:BATCH_SIZE]
    count   = 0
    failed  = 0
    emitter = SignalEmitter(_SIGNALS_DIR)
    log.info(f"Batch: {len(batch)} of {len(candidates)} image(s)")

    for img_path in batch:
        orig_rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
        is_tk    = _is_token(img_path)

        # --- Classification: face match for tokens, LLM for everything else ---
        clf: Optional[VisionClassification] = None
        matched_source: Optional[Path]      = None

        if is_tk:
            folder_candidates = _get_folder_candidates(img_path.parent, state)
            matched_source    = _try_face_match(img_path, folder_candidates)
            if matched_source is not None:
                matched_rel = matched_source.relative_to(_PROJECT_ROOT).as_posix()
                matched_sha = state["pathIndex"].get(matched_rel)
                if matched_sha and not matched_sha.startswith("path:"):
                    entry = state["images"].get(matched_sha)
                    if entry:
                        clf = _inherit_clf_from_state(entry)
                        log.info(
                            f"Token {img_path.name} → face-matched to "
                            f"{matched_source.name} (inherited meta)"
                        )

        if clf is None:
            try:
                clf = _classify_one(img_path, client, prompt, is_tk)
            except LLMOfflineError:
                log.warning(f"LLM offline while processing {img_path.name} — aborting batch")
                break
            except (LLMResponseError, Exception) as exc:
                log.error(f"Classification failed for {img_path.name}: {exc}")
                sha_fail = _sha256(img_path)
                state["images"][f"path:{orig_rel}"] = {
                    "path":          orig_rel,
                    "processedAt":   datetime.now(timezone.utc).isoformat(),
                    "originalName":  img_path.name,
                    "type":          "unknown",
                    "ancestry":      "none",
                    "class":         "none",
                    "creature_type": "none",
                    "element":       "none",
                    "environment":   "none",
                    "description":   "",
                    "sha256":        sha_fail,
                    "isToken":       is_tk,
                    "status":        "failed",
                }
                state["pathIndex"][orig_rel] = f"path:{orig_rel}"
                _save_state(state)
                failed += 1
                continue

        # --- Rename image (steps 4–6) ---
        try:
            img_path = _rename_image(img_path, clf)
        except Exception as exc:
            log.warning(f"Could not rename {img_path.name}: {exc} — using original path")

        new_rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
        sha     = _sha256(img_path)

        # --- Write draft (step 7) ---
        e_slug   = _entity_slug(clf)
        out_path = _resolve_entity_path(e_slug)
        _write_draft(out_path, clf, img_path, sha256=sha)

        # --- Append index (step 8) ---
        _append_index(img_path, clf, out_path.stem)
        log.info(f"Classified: {img_path.name} → {out_path.name} ({clf.type.value})")

        # --- Update processed-images.json (step 9) ---
        state["images"][sha] = {
            "path":          new_rel,
            "processedAt":   datetime.now(timezone.utc).isoformat(),
            "originalName":  img_path.name,
            "type":          clf.type.value,
            "ancestry":      clf.ancestry,
            "class":         clf.char_class,
            "creature_type": clf.creature_type,
            "element":       clf.element.value,
            "environment":   clf.environment.value,
            "description":   clf.description,
            "sha256":        sha,
            "isToken":       is_tk,
            "status":        "ok",
        }
        state["pathIndex"][new_rel] = sha
        _save_state(state)

        # --- Track face-match link in token-links.json ---
        if is_tk and matched_source is not None:
            matched_rel = matched_source.relative_to(_PROJECT_ROOT).as_posix()
            matched_sha = state["pathIndex"].get(matched_rel, "")
            token_links[sha] = {
                "tokenPath":   new_rel,
                "sourcePath":  matched_rel,
                "sourceSha256": matched_sha,
                "linkedAt":    datetime.now(timezone.utc).isoformat(),
            }
            _save_token_links(token_links)

        # --- Update inbox-queue.json (step 10) ---
        if orig_rel in queue and isinstance(queue[orig_rel].get("agents"), dict):
            queue[orig_rel]["agents"]["vision"] = "done"
            _save_queue(queue)

        # --- Emit signal for Lore agent (fire-and-forget per G5) ---
        emitter.emit(
            signal_type="image-classified",
            emitter=TASK_ID,
            ref=img_path.name,
        )

        count += 1

    log.done(t0, key="classified", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface (claude-api dispatch)
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
        "description": (
            "Check whether a PNG image is a circular token "
            "(transparent corner/edge pixels). Returns {is_token, path}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the PNG image",
                },
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "match_token_face",
        "description": (
            "Attempt to match a token image to its source portrait via face distance. "
            "Returns {matched: bool, source_path?, score?}. "
            "Only meaningful for PNG images detected as tokens."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the token PNG image",
                },
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "classify_image",
        "description": (
            "Classify a single image via the local vision LLM "
            "(type, ancestry, class, element, environment). "
            "Returns JSON classification. Does NOT rename the file or write a draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the image file",
                },
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "run_batch",
        "description": (
            "Classify up to BATCH_SIZE pending images, rename them to canonical slugs, "
            "and write draft entities to 01-Processing/. "
            "Returns log output including count processed."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import io
    import contextlib
    import json as _json

    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    if name == "list_pending_images":
        state      = _load_state()
        queue      = _load_queue()
        candidates = _candidate_images(state, queue)
        return _json.dumps([str(p) for p in candidates[:20]])

    if name == "detect_token":
        p = Path(args["image_path"])
        return _json.dumps({"is_token": _is_token(p), "path": str(p)})

    if name == "match_token_face":
        p = Path(args["image_path"])
        if not p.exists():
            return _json.dumps({"error": f"Image not found: {p}"})
        state       = _load_state()
        folder_cands = _get_folder_candidates(p.parent, state)
        matched     = _try_face_match(p, folder_cands)
        if matched is None:
            return _json.dumps({"matched": False, "candidates_checked": len(folder_cands)})
        return _json.dumps({
            "matched":     True,
            "source_path": str(matched),
        })

    if name == "classify_image":
        p = Path(args["image_path"])
        if not p.exists():
            return _json.dumps({"error": f"Image not found: {p}"})
        client = LLMClient(_LLM_CFG)
        if not client.is_available():
            return _json.dumps({"error": "LLM offline (localhost:1234)"})
        prompt = _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists() else ""
        is_tk  = _is_token(p)
        try:
            clf = _classify_one(p, client, prompt, is_tk)
            data = clf.model_dump()
            data["is_token"] = is_tk
            return _json.dumps(data)
        except LLMOfflineError:
            return _json.dumps({"error": "LLM offline"})
        except Exception as exc:
            return _json.dumps({"error": str(exc)})

    if name == "run_batch":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")
