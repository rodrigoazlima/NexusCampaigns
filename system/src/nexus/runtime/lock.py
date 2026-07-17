"""nexus.runtime.lock - single-instance process lock (runner.lock).

Separate from FileLock (nexus.shared.file_lock): this is a whole-process
"only one scheduler loop at a time" guard, not a scoped critical-section lock.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from nexus.shared import Logger

from .paths import LOCK_FILE, LOCK_STALE_SECONDS


def acquire_lock(log: Logger) -> bool:
    """Write PID + timestamp to lock file. Returns False if already locked."""
    if LOCK_FILE.exists():
        try:
            data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
            locked_at = datetime.fromisoformat(data["startedAt"])
            age = (datetime.now(timezone.utc) - locked_at).total_seconds()
            if age < LOCK_STALE_SECONDS:
                log.warning(f"Lock held by PID {data.get('pid')} since {data['startedAt']} ({age:.0f}s ago). Skipping.")
                return False
            log.warning(f"Stale lock detected ({age:.0f}s). Overriding.")
        except Exception:
            log.warning("Malformed lock file. Overriding.")

    payload = {"pid": os.getpid(), "startedAt": datetime.now(timezone.utc).isoformat()}
    LOCK_FILE.write_text(json.dumps(payload), encoding="utf-8")
    return True


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass
