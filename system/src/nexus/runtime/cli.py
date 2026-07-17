"""nexus.runtime.cli - argument parsing and process entrypoint for
`python -m nexus.runner` / `python system/src/nexus/runner.py`."""

from __future__ import annotations

import argparse
import sys
import time

from .chat import dispatch_chat
from .lock import acquire_lock, release_lock
from .log import make_logger
from .paths import DEFAULT_INTERVAL
from .registry_yaml import ensure_agent_jsons
from .scheduler import Runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vault Nexus Campaigns - agent runtime",
    )
    parser.add_argument("--once", action="store_true", help="Run one scheduling cycle then exit")
    parser.add_argument("--task", metavar="TASK_ID", default=None, help="Run only this specific task")
    parser.add_argument("--chat-id", metavar="UUID", default=None, help="Dispatch one chat queue item by ID then exit")
    parser.add_argument("--force", action="store_true", help="Bypass due-time and precondition checks (for testing)")
    parser.add_argument(
        "--ensure-config", action="store_true",
        help="Synthesize any missing agents/*/agent.json from registry.yaml defaults, then exit",
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL, metavar="SECONDS",
        help=f"Poll interval between cycles (default: {DEFAULT_INTERVAL}s)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log = make_logger("runtime")

    if args.ensure_config:
        ensure_agent_jsons(log)
        sys.exit(0)

    if args.chat_id:
        sys.exit(dispatch_chat(args.chat_id))

    if not acquire_lock(log):
        sys.exit(1)

    try:
        t0 = log.start()
        runtime = Runtime()

        if args.once or args.task:
            runtime.run_cycle(task_filter=args.task, force=args.force)
            log.done(t0, key="processed", count=0, failed=0)
        else:
            log.info(f"Entering scheduler loop (interval={args.interval}s)")
            while True:
                try:
                    runtime.run_cycle()
                except Exception as exc:
                    log.error(f"Cycle error: {exc}")
                time.sleep(args.interval)
    finally:
        release_lock()
