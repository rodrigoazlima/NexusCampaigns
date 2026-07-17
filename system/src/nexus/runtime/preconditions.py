"""nexus.runtime.preconditions — cheap "does this agent have work?" checks
that let the scheduler skip a dispatch (and its LLM tokens) up front.

LLM agents only — a skipped dispatch burns no tokens. Static work has no
preconditions: workers derive their own pending sets in pending().
"""

from __future__ import annotations

import json
from typing import Callable

from nexus.shared import Logger

from .paths import INBOX_QUEUE, PROJECT_ROOT


def read_inbox_queue() -> dict:
    if not INBOX_QUEUE.exists():
        return {}
    try:
        return json.loads(INBOX_QUEUE.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception:
        return {}


# vision only ever reads raw inbox files by extension (classify_images.py's
# own _IMAGE_EXTS — duplicated here per this codebase's existing manual-sync
# convention for cross-module constants, see vision CLAUDE.md's PF2E_* note).
# lore/classification/wiki slots legitimately point at non-image (document)
# entries too per state-files.spec.md's inbox-queue schema, so this filter
# is vision-specific, not applied to every slot.
_VISION_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def inbox_has_slot(slot: str) -> bool:
    """Return True if inbox-queue has at least one entry with agents.<slot> == 'pending'
    that points at a real, non-empty file the agent can actually process.

    Queue entries can outlive their file (renamed outside the normal vision-rename
    flow, deleted, or silently overwritten by a filename collision) and would
    otherwise stay 'pending' forever, triggering a dispatch every due cycle that
    can never actually complete the work. Skip those rather than treating them
    as pending.

    For vision specifically, also skip entries whose file isn't a recognized
    image extension (a mislabeled/misrouted queue entry) or is zero bytes (a
    placeholder mid-write) — dispatching the vision LLM against either wastes
    a cycle at best, and at worst feeds it bytes that aren't a decodable
    image, which is its own source of garbage/misinterpreted output.
    """
    queue = read_inbox_queue()
    for rel_path, entry in queue.items():
        agents = entry.get("agents", {}) if isinstance(entry, dict) else {}
        if agents.get(slot) != "pending":
            continue
        path = PROJECT_ROOT / rel_path
        if not path.is_file():
            continue
        if slot == "vision" and path.suffix.lower() not in _VISION_IMAGE_EXTS:
            continue
        if path.stat().st_size == 0:
            continue
        return True
    return False


# Map task_id → precondition function (returns bool; True = has work, False = skip).
PRECONDITIONS: dict[str, "Callable[[], bool]"] = {
    "vision-agent":         lambda: inbox_has_slot("vision"),
    "lore-agent":           lambda: inbox_has_slot("lore"),
    "classification-agent": lambda: inbox_has_slot("classification"),
    "wiki-agent":           lambda: inbox_has_slot("wiki"),
}


def check_preconditions(task_id: str, log: Logger) -> bool:
    """Return True if task has work. False = skip (no tokens consumed)."""
    check = PRECONDITIONS.get(task_id)
    if check is None:
        return True  # no precondition defined → always run
    try:
        result = check()
        if not result:
            log.info(f"Skip {task_id} — precondition: no pending work")
        return result
    except Exception as exc:
        log.warning(f"Precondition check failed for {task_id}: {exc} — running anyway")
        return True
