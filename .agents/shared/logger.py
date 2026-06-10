"""Concrete Logger — implements ILogger.

Writes [YYYY-MM-DD HH:mm:ss] [task_id] LEVEL: message to:
  - stdout (unbuffered)
  - master automation.log  (shared across all agents)
  - per-script daily rotation log  ({script_basename}_{YYYY-MM-DD}.log)
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path


class Logger:
    """Shared logger for all vault pipeline agents."""

    def __init__(
        self,
        task_id: str,
        script_basename: str,
        logs_dir: Path,
        master_log: Path,
    ) -> None:
        self.task_id = task_id
        logs_dir.mkdir(parents=True, exist_ok=True)
        master_log.parent.mkdir(parents=True, exist_ok=True)

        stem  = script_basename.removesuffix(".py").removesuffix(".ps1")
        today = datetime.now().strftime("%Y-%m-%d")

        self._daily  = logs_dir / f"{stem}_{today}.log"
        self._master = master_log

    def _write(self, level: str, message: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{self.task_id}] {level}: {message}"
        print(line, flush=True)
        for path in (self._master, self._daily):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, message: str)    -> None: self._write("INFO",  message)
    def warning(self, message: str) -> None: self._write("WARN",  message)
    def error(self, message: str)   -> None: self._write("ERROR", message)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, *, key: str, count: int, failed: int) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write(
            "INFO",
            f"--- DONE --- {key}: {count} failed={failed} elapsed={elapsed}s",
        )
