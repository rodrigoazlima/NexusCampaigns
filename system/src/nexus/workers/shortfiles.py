"""nexus.workers.shortfiles — draft QA gate (queue consumer, derived pending set).

Scans 01-Processing/ for .md drafts with fewer than MIN_BODY_LINES body
lines; sets needs_reprocessing: true and injects suggestedQuality: 0 when
quality: 0. Replaces nexus.tasks.flag_short_files.

seen.json (path → {mtime, verdict}) skips unchanged files — the one
behavior improvement over the task, which re-read every draft every run.

Guard rules: never writes 02-Library. 01-Processing frontmatter fields
needs_reprocessing + suggestedQuality only — never status/reviewed/quality.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from nexus.shared import FrontmatterIO, Logger, locked_update_queue_entry
from nexus.shared.loaders import _find_project_root
from nexus.workers.base import WorkItem, WorkResult, make_worker_logger, worker_state_dir

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

MIN_BODY_LINES = 10

_VAULT_ROOT  = _PROJECT_ROOT / ".knowledge-base"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_QUEUE_FILE  = _PROJECT_ROOT / "system" / "state" / "inbox-queue.json"


def _seen_file() -> Path:
    return worker_state_dir("shortfiles") / "seen.json"


def _load_seen() -> dict:
    p = _seen_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception:
        return {}


def _save_seen(seen: dict) -> None:
    p = _seen_file()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    tmp.replace(p)


def _load_queue() -> dict:
    if not _QUEUE_FILE.exists():
        return {}
    try:
        return json.loads(_QUEUE_FILE.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception:
        return {}


def _draft_source(fm: dict) -> str | None:
    """Return the first source path of a draft (normalized), or None."""
    src = fm.get("source")
    if isinstance(src, list) and src:
        return str(src[0]).replace("\\", "/")
    if isinstance(src, str) and src:
        return src.replace("\\", "/")
    return None


def _mark_review_done(source_rel: str, log: Logger) -> None:
    """Set agents.review = done in inbox-queue.json for the draft's source.
    Idempotent, locked, one entry at a time."""
    if not _QUEUE_FILE.exists():
        return
    try:
        queue = json.loads(_QUEUE_FILE.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception as exc:
        log.warning(f"Could not read inbox-queue.json: {exc}")
        return
    if source_rel not in queue:
        return

    def _mark(entry: dict) -> Optional[str]:
        agents = entry.setdefault("agents", {})
        if agents.get("review") != "done":
            agents["review"] = "done"
        return None

    locked_update_queue_entry(_QUEUE_FILE, source_rel, _mark)


class ShortfilesWorker:
    name = "shortfiles"
    kind = "queue"

    def __init__(self, options: dict | None = None) -> None:
        opts = options or {}
        self.min_body_lines = int(opts.get("min_body_lines", MIN_BODY_LINES))
        self._fio = FrontmatterIO()

    def pending(self) -> list[WorkItem]:
        """01-Processing .md files not yet measured at their current mtime."""
        if not _PROCESSING.exists():
            return []
        seen = _load_seen()
        items: list[WorkItem] = []
        for md_path in sorted(_PROCESSING.glob("**/*.md")):
            rel = md_path.relative_to(_PROJECT_ROOT).as_posix()
            mtime = md_path.stat().st_mtime
            entry = seen.get(rel)
            if entry and entry.get("mtime") == mtime:
                continue
            items.append(WorkItem(rel, {"mtime": mtime}))
        return items

    def handle(self, item: WorkItem) -> WorkResult:
        log = make_worker_logger(self.name)
        md_path = _PROJECT_ROOT / item.key
        if not md_path.exists():
            return WorkResult("skip", "file gone")

        seen = _load_seen()
        mtime = item.payload.get("mtime", md_path.stat().st_mtime)

        try:
            fm, body = self._fio.read(md_path)
        except Exception as exc:
            # Unparseable frontmatter needs a human fix; retrying is useless.
            seen[item.key] = {"mtime": mtime, "verdict": "unparseable"}
            _save_seen(seen)
            log.warning(f"Read error {md_path.name}: {exc}")
            return WorkResult("skip", f"unparseable frontmatter: {md_path.name}")

        src = _draft_source(fm)
        if src and _load_queue().get(src, {}).get("agents", {}).get("review") == "paused":
            return WorkResult("skip", f"source paused: {src}")
        if src:
            _mark_review_done(src, log)

        body_lines = [ln for ln in body.splitlines() if ln.strip()]
        if len(body_lines) >= self.min_body_lines:
            seen[item.key] = {"mtime": mtime, "verdict": "ok"}
            _save_seen(seen)
            return WorkResult("skip", f"{len(body_lines)} body lines — long enough")

        changed = False
        if not fm.get("needs_reprocessing"):
            fm["needs_reprocessing"] = True
            changed = True
        if fm.get("quality", 0) == 0 and "suggestedQuality" not in fm:
            fm["suggestedQuality"] = 0
            changed = True
        if changed:
            self._fio.write(md_path, fm, body)
            # flag write bumps mtime — record the post-write mtime so the
            # file is not re-picked next cycle
            mtime = md_path.stat().st_mtime

        seen[item.key] = {"mtime": mtime, "verdict": "flagged"}
        _save_seen(seen)
        log.warning(f"Short file ({len(body_lines)} body lines): {item.key}")
        return WorkResult("done", f"flagged ({len(body_lines)} body lines)")


def create(options: dict | None = None) -> ShortfilesWorker:
    return ShortfilesWorker(options)


if __name__ == "__main__":
    worker = create()
    for _item in worker.pending():
        _res = worker.handle(_item)
        print(f"{_res.status} {_item.key}: {_res.detail}")
