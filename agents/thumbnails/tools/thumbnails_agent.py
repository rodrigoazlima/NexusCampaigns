"""thumbnails.tools.thumbnails_agent

Thumbnail agent — no LLM, no vault writes.

Pre-generates 320px-wide webp thumbnails for every image in the inbox queue
(system/state/inbox-queue.json) into system/state/thumbs/<sha1(path)>.webp,
where <path> is the queue key normalized to forward slashes. The dashboard's
/api/image?thumb=1 route serves these, falling back to the original when a
thumb is missing.

Incremental: existing thumbs are skipped; thumbs whose queue entry is gone
are pruned. Per-image failures are logged and skipped, never fatal.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import Logger  # noqa: E402

TASK_ID         = "thumbnails-agent"
SCRIPT_BASENAME = "thumbnails_agent.py"

_QUEUE_FILE  = _PROJECT_ROOT / "system" / "state" / "inbox-queue.json"
_THUMBS_DIR  = _PROJECT_ROOT / "system" / "state" / "thumbs"
_LOGS_DIR    = _AGENTS_DIR / "thumbnails" / "state" / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"

THUMB_WIDTH = 320
WEBP_QUALITY = 80
# Pillow-readable raster formats only (.svg is vector — served as-is by the dashboard)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


def _thumb_key(queue_path: str) -> str:
    return hashlib.sha1(queue_path.replace("\\", "/").encode("utf-8")).hexdigest()


def _generate_thumb(src: Path, dest: Path) -> None:
    from PIL import Image

    with Image.open(src) as img:
        img.load()  # first frame of animated gif/webp
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        if img.width > THUMB_WIDTH:
            height = max(1, round(img.height * THUMB_WIDTH / img.width))
            img = img.resize((THUMB_WIDTH, height), Image.LANCZOS)
        tmp = dest.with_suffix(".tmp")
        img.save(tmp, "WEBP", quality=WEBP_QUALITY)
    tmp.replace(dest)


def main() -> int:
    log = _make_logger()
    t0 = log.start()

    try:
        queue: dict = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error(f"cannot read inbox queue: {exc}")
        log.done(t0, key="generated", count=0, failed=1)
        return 1

    _THUMBS_DIR.mkdir(parents=True, exist_ok=True)

    wanted: dict[str, str] = {}  # sha1 -> queue path
    for queue_path in queue:
        if Path(queue_path).suffix.lower() in IMAGE_EXTS:
            wanted[_thumb_key(queue_path)] = queue_path

    generated = 0
    failed = 0
    for key, queue_path in wanted.items():
        dest = _THUMBS_DIR / f"{key}.webp"
        if dest.exists():
            continue
        src = _PROJECT_ROOT / queue_path
        if not src.exists():
            continue  # queue entry for a deleted file — nothing to thumbnail
        try:
            _generate_thumb(src, dest)
            generated += 1
        except Exception as exc:
            failed += 1
            log.warning(f"thumb failed for {queue_path}: {exc}")

    # Prune thumbs whose queue entry is gone
    pruned = 0
    for f in _THUMBS_DIR.glob("*.webp"):
        if f.stem not in wanted:
            try:
                f.unlink()
                pruned += 1
            except OSError as exc:
                log.warning(f"prune failed for {f.name}: {exc}")
    if pruned:
        log.info(f"pruned {pruned} orphan thumbs")

    log.done(t0, key="generated", count=generated, failed=failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
