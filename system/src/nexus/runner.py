"""nexus.runner

Python runtime — the scheduler for the agent pipeline. Entrypoint only; the
implementation lives in nexus.runtime (see nexus/runtime/__init__.py for the
module map), split by responsibility per SOLID.

CLI: python -m nexus.runner [--once] [--task TASK_ID] [--interval SECONDS]
     python -m nexus.runner --chat-id <uuid>   # dispatch one chat queue item
"""

from __future__ import annotations

from nexus.runtime.cli import main

if __name__ == "__main__":
    main()
