"""Locked, single-item read-modify-write for system/state/inbox-queue.json.

Every agent tool that touches the shared inbox queue must persist one item
at a time through this helper instead of buffering a whole batch in memory
and saving once - otherwise two agents running concurrently (pipeline_mode:
async) can clobber each other's updates, and a crash mid-batch loses all
progress made before the final save.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .file_lock import FileLock


def _load(queue_file: Path) -> dict:
    if not queue_file.exists():
        return {}
    text = queue_file.read_text(encoding="utf-8").lstrip("﻿")
    return json.loads(text) if text.strip() else {}


def _save(queue_file: Path, queue: dict) -> None:
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = queue_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
    tmp.replace(queue_file)


def locked_update_queue_entry(
    queue_file: Path,
    rel_key: str,
    mutate: Callable[[dict], Optional[str]],
) -> None:
    """Reload the queue fresh under lock, mutate one entry, save, release.

    `mutate(entry)` receives the entry dict for `rel_key` (empty dict if new)
    and mutates it in place. It may return a new key to rename the entry to
    (e.g. vision renaming a hashed filename to a descriptive slug) - the old
    key is dropped in that case.
    """
    with FileLock(queue_file):
        queue = _load(queue_file)
        entry = queue.get(rel_key, {})
        new_key = mutate(entry)
        if new_key and new_key != rel_key:
            queue.pop(rel_key, None)
            queue[new_key] = entry
        else:
            queue[rel_key] = entry
        _save(queue_file, queue)
