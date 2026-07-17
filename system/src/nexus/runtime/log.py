"""nexus.runtime.log - wires up the shared Logger for the runtime.

The runtime's log format is identical to every other agent's (same class,
`nexus.shared.Logger`); this module only supplies the runtime's own
logs-dir/master-log/script-name so callers don't repeat those four args.
"""

from __future__ import annotations

from nexus.shared import Logger

from .paths import LOGS_DIR, MASTER_LOG


def make_logger(task_id: str = "runtime") -> Logger:
    return Logger(task_id, "runner", LOGS_DIR, MASTER_LOG)
