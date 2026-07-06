"""Cross-process advisory file lock — blocking variant of runner.py's lock pattern.

Used to serialize read-modify-write access to files shared across agent
processes (inbox-queue.json, tasks-state.json) when the pipeline runs agents
concurrently (pipeline_mode: async in registry.yaml).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

_STALE_SECONDS = 60.0
_POLL_SECONDS = 0.05


class FileLock:
    """Context manager. Blocks until the lock file can be created exclusively.

    Stale locks (older than _STALE_SECONDS, e.g. left by a crashed process)
    are overridden rather than blocking forever.
    """

    def __init__(self, target: Path, timeout: float = 10.0) -> None:
        self._lock_path = target.with_name(target.name + ".lock")
        self._timeout = timeout

    def __enter__(self) -> "FileLock":
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self._lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > _STALE_SECONDS:
                    self._lock_path.unlink(missing_ok=True)
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Could not acquire lock {self._lock_path} within {self._timeout}s")
                time.sleep(_POLL_SECONDS)

    def __exit__(self, *exc_info: object) -> None:
        self._lock_path.unlink(missing_ok=True)
