"""nexus.workers.thumbnails - dashboard thumbnail cache warmer (queue consumer).

Pre-generates 320px-wide webp thumbnails for every image entry in the inbox
queue into system/state/thumbs/<sha1(queue-key)>.webp; prunes thumbs whose
queue entry is gone. Replaces nexus.tasks.thumbnails_agent.

No inbox-queue slot: the thumb file's existence IS the done-marker (cheap
to stat, self-healing when a thumb is deleted). No vault writes, no commits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nexus.shared.logging import image_tag
from nexus.shared.loaders import _find_project_root
from nexus.workers.base import WorkItem, WorkResult, make_worker_logger

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

_STATE_ROOT  = _PROJECT_ROOT / "system" / "state"
_QUEUE_FILE  = _STATE_ROOT / "inbox-queue.json"
_THUMBS_DIR  = _STATE_ROOT / "thumbs"

THUMB_WIDTH  = 320
WEBP_QUALITY = 80
# Pillow-readable raster formats only (.svg is vector - served as-is by the dashboard)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

_warned_no_pillow = False


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


def _wanted_thumbs() -> dict[str, str]:
    """sha1 → queue path for every image entry in the inbox queue."""
    try:
        queue: dict = json.loads(_QUEUE_FILE.read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        _thumb_key(qp): qp
        for qp in queue
        if Path(qp).suffix.lower() in IMAGE_EXTS
    }


class ThumbnailsWorker:
    name = "thumbnails"
    kind = "queue"

    def __init__(self, options: dict | None = None) -> None:
        pass

    def pending(self) -> list[WorkItem]:
        global _warned_no_pillow
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            if not _warned_no_pillow:
                make_worker_logger(self.name).warning("Pillow not installed - thumbnails disabled")
                _warned_no_pillow = True
            return []

        wanted = _wanted_thumbs()
        if not wanted and not _THUMBS_DIR.exists():
            return []

        items: list[WorkItem] = []
        for key, queue_path in wanted.items():
            dest = _THUMBS_DIR / f"{key}.webp"
            if dest.exists():
                continue
            if not (_PROJECT_ROOT / queue_path).exists():
                continue  # queue entry for a deleted file - nothing to thumbnail
            items.append(WorkItem(queue_path, {"action": "generate", "thumb": f"{key}.webp"}))

        if _THUMBS_DIR.exists():
            for f in _THUMBS_DIR.glob("*.webp"):
                if f.stem not in wanted:
                    items.append(WorkItem(f.name, {"action": "prune"}))

        return items

    def handle(self, item: WorkItem) -> WorkResult:
        log = make_worker_logger(self.name)

        if item.payload.get("action") == "prune":
            try:
                (_THUMBS_DIR / item.key).unlink(missing_ok=True)
                return WorkResult("done", f"pruned orphan thumb {item.key}")
            except OSError as exc:
                return WorkResult("error", f"prune failed for {item.key}: {exc}")

        src  = _PROJECT_ROOT / item.key
        dest = _THUMBS_DIR / item.payload["thumb"]
        if dest.exists():
            return WorkResult("skip", "thumb already exists")
        _THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            _generate_thumb(src, dest)
            return WorkResult("done", f"thumb for {item.key}")
        except Exception as exc:
            # Corrupt/unreadable image: retrying cannot fix the source file,
            # and the dashboard falls back to the original - skip, not error.
            log.warning(f"thumb failed: {exc}{image_tag(path=item.key)}")
            return WorkResult("skip", f"unreadable image: {exc}")


def create(options: dict | None = None) -> ThumbnailsWorker:
    return ThumbnailsWorker(options)


if __name__ == "__main__":
    worker = create()
    for _item in worker.pending():
        _res = worker.handle(_item)
        print(f"{_res.status} {_item.key}: {_res.detail}")
