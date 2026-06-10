"""orchestrator.tools.runner

Concrete IOrchestrator implementation.
Entry point for Windows Task Scheduler.
CLI: python runner.py [--once] [--task TASK_ID] [--interval SECONDS]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# .agents/ must be on sys.path so `import shared` resolves
_AGENTS_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _AGENTS_DIR.parent
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    IOrchestrator,
    TasksConfig,
    TasksState,
    TaskStateEntry,
    TASKS_STATE_DEFAULT,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ORCH_STATE  = Path(__file__).resolve().parents[1] / "state"
_TASKS_JSON  = _ORCH_STATE / "tasks.json"
_STATE_JSON  = _ORCH_STATE / "tasks-state.json"
_LOCK_FILE   = _ORCH_STATE / "runner.lock"
_LOGS_DIR    = _ORCH_STATE / "logs"
_MASTER_LOG  = _LOGS_DIR / "automation.log"

_LOCK_STALE_SECONDS = 1800   # 30 min
_DEFAULT_INTERVAL   = 60     # orchestrator poll cadence


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class _Logger:
    """Writes [YYYY-MM-DD HH:mm:ss] [task_id] message to files + stdout."""

    def __init__(self, task_id: str = "orchestrator") -> None:
        self.task_id = task_id
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily = _LOGS_DIR / f"runner_{today}.log"

    def _write(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{self.task_id}] {level}: {message}"
        print(line, flush=True)
        for path in (_MASTER_LOG, self._daily):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, msg: str) -> None:
        self._write("INFO", msg)

    def warning(self, msg: str) -> None:
        self._write("WARN", msg)

    def error(self, msg: str) -> None:
        self._write("ERROR", msg)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, *, count: int = 0, failed: int = 0) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write("INFO", f"--- DONE --- processed={count} failed={failed} elapsed={elapsed}s")


# ---------------------------------------------------------------------------
# Lock file helpers
# ---------------------------------------------------------------------------

def _acquire_lock(log: _Logger) -> bool:
    """Write PID + timestamp to lock file. Returns False if already locked."""
    if _LOCK_FILE.exists():
        try:
            data = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
            locked_at = datetime.fromisoformat(data["startedAt"])
            age = (datetime.now(timezone.utc) - locked_at).total_seconds()
            if age < _LOCK_STALE_SECONDS:
                log.warning(f"Lock held by PID {data.get('pid')} since {data['startedAt']} ({age:.0f}s ago). Skipping.")
                return False
            log.warning(f"Stale lock detected ({age:.0f}s). Overriding.")
        except Exception:
            log.warning("Malformed lock file. Overriding.")

    payload = {"pid": os.getpid(), "startedAt": datetime.now(timezone.utc).isoformat()}
    _LOCK_FILE.write_text(json.dumps(payload), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def _load_tasks() -> TasksConfig:
    raw = json.loads(_TASKS_JSON.read_text(encoding="utf-8"))
    return TasksConfig.model_validate(raw)


def _load_state() -> TasksState:
    if not _STATE_JSON.exists():
        _STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        _STATE_JSON.write_text(
            json.dumps(TASKS_STATE_DEFAULT, indent=2),
            encoding="utf-8",
        )
    raw: dict = json.loads(_STATE_JSON.read_text(encoding="utf-8"))
    return {k: TaskStateEntry.model_validate(v) for k, v in raw.items()}


def _save_state(state: TasksState) -> None:
    tmp = _STATE_JSON.with_suffix(".tmp")
    payload = {k: {"lastRun": v.lastRun.isoformat()} for k, v in state.items()}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(_STATE_JSON)


# ---------------------------------------------------------------------------
# Agent AGENT.md commit scope reader
# ---------------------------------------------------------------------------

_YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_COMMIT_SCOPE_RE     = re.compile(r"^commit_scope:\s*\n((?:[ \t]+-[^\n]+\n?)+)", re.MULTILINE)
_SCOPE_ITEM_RE       = re.compile(r"^\s+-\s+(.+)$", re.MULTILINE)


def _agent_name_from_task_id(task_id: str) -> Optional[str]:
    """Map task_id → agent directory name (strip -agent suffix, handle exceptions)."""
    # Tasks: ingestion-agent → ingestion, review-agent-short-files → review
    name = task_id.replace("-agent-short-files", "").replace("-agent", "")
    return name or None


def _read_agent_commit_scope(task_id: str) -> list[str]:
    """Parse commit_scope from the agent's AGENT.md. Returns [] if absent."""
    agent_name = _agent_name_from_task_id(task_id)
    if not agent_name:
        return []
    agent_md = _AGENTS_DIR / agent_name / "AGENT.md"
    if not agent_md.exists():
        return []
    try:
        content = agent_md.read_text(encoding="utf-8")
        m = _COMMIT_SCOPE_RE.search(content)
        if not m:
            return []
        return [item.strip() for item in _SCOPE_ITEM_RE.findall(m.group(1)) if item.strip()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator(IOrchestrator):
    """Schedules and dispatches vault agents sequentially."""

    def __init__(self) -> None:
        self._tasks_cfg: Optional[TasksConfig] = None
        self._state: Optional[TasksState] = None
        self._log = _Logger("orchestrator")

    # IOrchestrator ---------------------------------------------------------

    def is_due(self, task_id: str) -> bool:
        """Return True if elapsed since lastRun >= intervalSeconds."""
        cfg = self._get_task_cfg(task_id)
        if cfg is None:
            return False
        state = self._state or {}
        entry = state.get(task_id)
        if entry is None:
            return True  # never ran
        now = datetime.now(timezone.utc)
        last = entry.lastRun
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (now - last).total_seconds()
        return elapsed >= cfg.intervalSeconds

    def dispatch(self, task_id: str) -> int:
        """Run agent script as subprocess. Returns exit code."""
        cfg = self._get_task_cfg(task_id)
        if cfg is None:
            self._log.error(f"Task not found: {task_id}")
            return 1

        script_path = _PROJECT_ROOT / cfg.script
        if not script_path.exists():
            self._log.error(f"Script not found: {script_path}")
            return 1

        log = _Logger(task_id)
        t0 = log.start()

        cmd = [sys.executable, str(script_path)]
        log.info(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(_PROJECT_ROOT),
                capture_output=False,   # let output stream to console
                text=True,
            )
            exit_code = result.returncode
        except Exception as exc:
            log.error(f"Subprocess error: {exc}")
            exit_code = 1

        log.done(t0, count=1 if exit_code == 0 else 0, failed=0 if exit_code == 0 else 1)
        return exit_code

    def commit_changes(self, task_id: str) -> None:
        """Stage only the agent's declared commit_scope, then commit if dirty."""
        scope = _read_agent_commit_scope(task_id)
        if not scope:
            self._log.warning(
                f"No commit_scope declared for {task_id} — skipping git commit"
            )
            return

        # Stage only the declared paths
        for path in scope:
            subprocess.run(
                ["git", "add", "--", path],
                cwd=str(_PROJECT_ROOT),
                capture_output=True,
            )

        # Check if anything is actually staged
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(_PROJECT_ROOT),
        )
        if staged.returncode == 0:
            return  # nothing staged — nothing to commit

        ts  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = f"chore(auto): {task_id} run at {ts}"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(_PROJECT_ROOT),
            check=True,
        )
        self._log.info(f"Committed scoped changes for {task_id} (paths: {scope})")

    # Internals -------------------------------------------------------------

    def _get_task_cfg(self, task_id: str):
        if self._tasks_cfg is None:
            return None
        for t in self._tasks_cfg.tasks:
            if t.id == task_id:
                return t
        return None

    def reload(self) -> None:
        """Reload tasks.json and tasks-state.json from disk."""
        self._tasks_cfg = _load_tasks()
        self._state = _load_state()

    def run_cycle(self, task_filter: Optional[str] = None) -> None:
        """One scheduling cycle: check all tasks, dispatch due ones."""
        self.reload()
        assert self._tasks_cfg is not None
        assert self._state is not None

        for task in self._tasks_cfg.tasks:
            if task_filter and task.id != task_filter:
                continue

            if not self.is_due(task.id):
                self._log.info(f"Skip {task.id} — not yet due")
                continue

            self._log.info(f"Dispatching {task.id} ({task.description})")
            exit_code = self.dispatch(task.id)

            # Update lastRun regardless of exit code
            self._state[task.id] = TaskStateEntry(
                lastRun=datetime.now(timezone.utc)
            )
            _save_state(self._state)

            if exit_code == 0:
                try:
                    self.commit_changes(task.id)
                except Exception as exc:
                    self._log.warning(f"Git commit failed for {task.id}: {exc}")
            else:
                self._log.warning(f"Task {task.id} exited with code {exit_code} — skipping git commit")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vault Knowledge Factory — orchestrator runner",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scheduling cycle then exit",
    )
    parser.add_argument(
        "--task",
        metavar="TASK_ID",
        default=None,
        help="Run only this specific task",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=_DEFAULT_INTERVAL,
        metavar="SECONDS",
        help=f"Poll interval between cycles (default: {_DEFAULT_INTERVAL}s)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    log = _Logger("orchestrator")

    if not _acquire_lock(log):
        sys.exit(1)

    try:
        t0 = log.start()
        orch = Orchestrator()

        if args.once or args.task:
            orch.run_cycle(task_filter=args.task)
            log.done(t0)
        else:
            log.info(f"Entering scheduler loop (interval={args.interval}s)")
            while True:
                try:
                    orch.run_cycle()
                except Exception as exc:
                    log.error(f"Cycle error: {exc}")
                time.sleep(args.interval)
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
