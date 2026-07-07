"""nexus.tasks.flag_short_files

Scans 01-Processing/ for draft .md files with fewer than 10 body lines.
Sets needs_reprocessing: true in frontmatter and injects suggestedQuality: 0
when quality: 0 and suggestedQuality is absent.
No LLM. No 02-Library writes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from nexus.shared import FrontmatterIO, Logger, locked_update_queue_entry
from nexus.shared.loaders import _find_project_root

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

TASK_ID         = "review-agent-short-files"
SCRIPT_BASENAME = "flag_short_files.py"
MIN_BODY_LINES  = 10

_VAULT_ROOT  = _PROJECT_ROOT / ".knowledge-base"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_STATE_ROOT  = _PROJECT_ROOT / "system" / "state"
_LOGS_DIR    = _STATE_ROOT / "review" / "logs"
_MASTER_LOG  = _STATE_ROOT / "runtime" / "logs" / "automation.log"
_QUEUE_FILE  = _STATE_ROOT / "inbox-queue.json"


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


def _flag_short_file(path: Path, fio: FrontmatterIO, log: Logger) -> None:
    """Set needs_reprocessing: true and inject suggestedQuality: 0 if applicable."""
    try:
        fm, body = fio.read(path)
        changed = False
        if not fm.get("needs_reprocessing"):
            fm["needs_reprocessing"] = True
            changed = True
        if fm.get("quality", 0) == 0 and "suggestedQuality" not in fm:
            fm["suggestedQuality"] = 0
            changed = True
        if changed:
            fio.write(path, fm, body)
    except Exception as exc:
        log.warning(f"Could not flag {path.name}: {exc}")


def _draft_source(fm: dict) -> str | None:
    """Return the first source path of a draft (normalized), or None."""
    src = fm.get("source")
    if isinstance(src, list) and src:
        return str(src[0]).replace("\\", "/")
    if isinstance(src, str) and src:
        return src.replace("\\", "/")
    return None


def _mark_reviewed(sources: set[str], log: Logger) -> int:
    """Set agents.review = done in inbox-queue.json for each source the review
    pass scanned. Idempotent, locked, one entry at a time. Returns the number
    of queue entries updated."""
    if not sources or not _QUEUE_FILE.exists():
        return 0
    try:
        queue = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(f"Could not read inbox-queue.json: {exc}")
        return 0

    updated = 0
    for rel in sources:
        if rel not in queue:
            continue

        changed = False

        def _mark(entry: dict) -> Optional[str]:
            nonlocal changed
            agents = entry.setdefault("agents", {})
            if agents.get("review") != "done":
                agents["review"] = "done"
                changed = True
            return None

        locked_update_queue_entry(_QUEUE_FILE, rel, _mark)
        if changed:
            updated += 1

    if updated:
        log.info(f"Marked agents.review=done for {updated} queue entry/entries")
    return updated


def main() -> None:
    log = _make_logger()
    t0  = log.start()
    fio = FrontmatterIO()
    flagged = 0
    scanned = 0
    reviewed_sources: set[str] = set()

    if not _PROCESSING.exists():
        log.info("01-Processing/ does not exist — nothing to scan")
        log.done(t0, key="processed", count=0, failed=0)
        sys.exit(0)

    for md_path in sorted(_PROCESSING.glob("**/*.md")):
        scanned += 1
        try:
            fm, body = fio.read(md_path)
        except Exception as exc:
            log.warning(f"Read error {md_path.name}: {exc}")
            continue

        src = _draft_source(fm)
        if src:
            reviewed_sources.add(src)

        body_lines = [ln for ln in body.splitlines() if ln.strip()]
        if len(body_lines) < MIN_BODY_LINES:
            flagged += 1
            log.warning(
                f"Short file ({len(body_lines)} body lines): {md_path.relative_to(_PROJECT_ROOT).as_posix()}"
            )
            _flag_short_file(md_path, fio, log)

    _mark_reviewed(reviewed_sources, log)

    log.info(f"Scanned {scanned} files — {flagged} flagged as short (< {MIN_BODY_LINES} lines)")
    log.done(t0, key="processed", count=flagged, failed=0)
    sys.exit(0)


if __name__ == "__main__":
    main()
