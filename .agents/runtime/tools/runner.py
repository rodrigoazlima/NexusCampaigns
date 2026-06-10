"""runtime.tools.runner

Python runtime — the only static code in the agent pipeline.
Discovers agents from agent.json files, checks intervals, dispatches Claude agents.

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
_AGENTS_DIR  = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _AGENTS_DIR.parent
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    AgentDispatchConfig,
    AgentFolderConfig,
    DispatchError,
    IOrchestrator,
    TasksState,
    TaskStateEntry,
    TaskDispatchEntry,
    get_runner,
    TASKS_STATE_DEFAULT,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_RUNTIME_STATE = Path(__file__).resolve().parents[1] / "state"
_STATE_JSON    = _RUNTIME_STATE / "tasks-state.json"
_LOCK_FILE     = _RUNTIME_STATE / "runner.lock"
_LOGS_DIR      = _RUNTIME_STATE / "logs"
_MASTER_LOG    = _LOGS_DIR / "automation.log"

_LOCK_STALE_SECONDS = 1800   # 30 min
_DEFAULT_INTERVAL   = 60     # orchestrator poll cadence

# Maps dispatch.type → attribute name on AgentDispatchConfig
_DISPATCH_TYPE_FIELD: dict[str, str] = {
    "cli":            "cli",
    "openai-api":     "openai_api",
    "claude-api":     "claude_api",
    "gemini-api":     "gemini_api",
    "openrouter-api": "openrouter_api",
}


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class _Logger:
    """Writes [YYYY-MM-DD HH:mm:ss] [task_id] message to files + stdout."""

    def __init__(self, task_id: str = "runtime") -> None:
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
# Task discovery — reads agent.json files, no tasks.json
# ---------------------------------------------------------------------------

def _discover_tasks() -> list[tuple[str, TaskDispatchEntry]]:
    """Scan .agents/*/agent.json and return all (task_id, TaskDispatchEntry) pairs."""
    result: list[tuple[str, TaskDispatchEntry]] = []
    for agent_json in sorted(_AGENTS_DIR.glob("*/agent.json")):
        try:
            raw = json.loads(agent_json.read_text(encoding="utf-8"))
            folder = AgentFolderConfig.model_validate(raw)
            for task_id, entry in folder.tasks.items():
                result.append((task_id, entry))
        except Exception as exc:
            _Logger().warning(f"Skipping {agent_json}: {exc}")
    return result


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

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
# Agent name resolution and agent.json loading
# ---------------------------------------------------------------------------

_COMMIT_SCOPE_RE = re.compile(r"^commit_scope:\s*\n((?:[ \t]+-[^\n]+\n?)+)", re.MULTILINE)
_SCOPE_ITEM_RE   = re.compile(r"^\s+-\s+(.+)$", re.MULTILINE)


def _agent_name_from_task_id(task_id: str) -> str:
    """Map task_id → agent directory name.

    Examples:
      repair-agent              → repair
      review-agent              → review
      review-agent-short-files  → review
    """
    name = re.sub(r"-agent(?:-.*)?$", "", task_id)
    return name or task_id


def _load_agent_dispatch(task_id: str, log: _Logger) -> Optional[AgentDispatchConfig]:
    """Load and return the AgentDispatchConfig for task_id from agent.json."""
    agent_name = _agent_name_from_task_id(task_id)
    agent_json = _AGENTS_DIR / agent_name / "agent.json"

    if not agent_json.exists():
        log.error(f"agent.json not found: {agent_json} — skipping {task_id}")
        return None

    try:
        raw = json.loads(agent_json.read_text(encoding="utf-8"))
        folder_cfg = AgentFolderConfig.model_validate(raw)
    except Exception as exc:
        log.error(f"Failed to parse {agent_json}: {exc} — skipping {task_id}")
        return None

    entry: Optional[TaskDispatchEntry] = folder_cfg.tasks.get(task_id)
    if entry is None:
        log.error(f"Task ID {task_id!r} not found in {agent_json} — skipping")
        return None

    return entry.dispatch


def _read_agent_commit_scope(task_id: str) -> list[str]:
    """Parse commit_scope from the agent's AGENT.md. Returns [] if absent."""
    agent_name = _agent_name_from_task_id(task_id)
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


def _extract_dispatch_sub(dispatch: AgentDispatchConfig) -> dict:
    """Return the type-specific sub-config as a plain dict."""
    field = _DISPATCH_TYPE_FIELD.get(dispatch.type)
    if field is None:
        raise DispatchError(f"Unknown dispatch type: {dispatch.type!r}")
    sub = getattr(dispatch, field, None)
    if sub is None:
        raise DispatchError(
            f"Dispatch type is {dispatch.type!r} but the '{field}' block is absent in agent.json"
        )
    return sub.model_dump()


# ---------------------------------------------------------------------------
# Runtime (replaces orchestrator)
# ---------------------------------------------------------------------------

class Runtime(IOrchestrator):
    """Discovers agents from agent.json files, schedules and dispatches them."""

    def __init__(self) -> None:
        self._tasks: list[tuple[str, TaskDispatchEntry]] = []
        self._state: Optional[TasksState] = None
        self._log = _Logger("runtime")

    # IOrchestrator ---------------------------------------------------------

    def is_due(self, task_id: str) -> bool:
        entry = self._get_task_entry(task_id)
        if entry is None:
            return False
        state = self._state or {}
        run_entry = state.get(task_id)
        if run_entry is None:
            return True  # never ran
        now = datetime.now(timezone.utc)
        last = run_entry.lastRun
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds() >= entry.intervalSeconds

    def load_agent_dispatch(self, task_id: str) -> Optional[AgentDispatchConfig]:
        return _load_agent_dispatch(task_id, self._log)

    def dispatch(self, task_id: str) -> int:
        entry = self._get_task_entry(task_id)
        if entry is None:
            self._log.error(f"Task not found in any agent.json: {task_id}")
            return 1

        dispatch_cfg = _load_agent_dispatch(task_id, self._log)
        if dispatch_cfg is None:
            return 1

        log = _Logger(task_id)
        t0 = log.start()
        exit_code = 1

        try:
            sub_config = _extract_dispatch_sub(dispatch_cfg)
            runner = get_runner(dispatch_cfg.type)
            agent_name = _agent_name_from_task_id(task_id)
            context = {
                "project_root": str(_PROJECT_ROOT),
                "agents_dir":   str(_AGENTS_DIR),
                "agent_dir":    str(_AGENTS_DIR / agent_name),
                "task_id":      task_id,
                "master_log":   str(_MASTER_LOG),
            }
            log.info(f"Dispatching via {dispatch_cfg.type}: {sub_config.get('tools_module', sub_config.get('command', dispatch_cfg.type))}")
            result = runner.run(sub_config, context)
            exit_code = result.exit_code
            if result.error:
                log.error(f"Runner error: {result.error}")
        except DispatchError as exc:
            log.error(f"Dispatch config error: {exc}")
        except NotImplementedError as exc:
            log.error(f"Runner not implemented: {exc}")
        except Exception as exc:
            log.error(f"Unexpected dispatch error: {exc}")

        log.done(t0, count=1 if exit_code == 0 else 0, failed=0 if exit_code == 0 else 1)
        return exit_code

    def commit_changes(self, task_id: str) -> None:
        scope = _read_agent_commit_scope(task_id)
        if not scope:
            self._log.warning(
                f"No commit_scope declared for {task_id} — skipping git commit"
            )
            return

        for path in scope:
            subprocess.run(
                ["git", "add", "--", path],
                cwd=str(_PROJECT_ROOT),
                capture_output=True,
            )

        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(_PROJECT_ROOT),
        )
        if staged.returncode == 0:
            return

        ts  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = f"chore(auto): {task_id} run at {ts}"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(_PROJECT_ROOT),
            check=True,
        )
        self._log.info(f"Committed scoped changes for {task_id} (paths: {scope})")

    # Internals -------------------------------------------------------------

    def _get_task_entry(self, task_id: str) -> Optional[TaskDispatchEntry]:
        for tid, entry in self._tasks:
            if tid == task_id:
                return entry
        return None

    def reload(self) -> None:
        """Discover tasks from agent.json files and reload run state."""
        self._tasks = _discover_tasks()
        self._state = _load_state()
        self._log.info(f"Discovered {len(self._tasks)} tasks from agent.json files")

    def run_cycle(self, task_filter: Optional[str] = None) -> None:
        """One scheduling cycle: check all tasks, dispatch due ones."""
        self.reload()

        for task_id, entry in self._tasks:
            if task_filter and task_id != task_filter:
                continue

            if not self.is_due(task_id):
                self._log.info(f"Skip {task_id} — not yet due")
                continue

            self._log.info(f"Dispatching {task_id} ({entry.description})")
            exit_code = self.dispatch(task_id)

            assert self._state is not None
            self._state[task_id] = TaskStateEntry(
                lastRun=datetime.now(timezone.utc)
            )
            _save_state(self._state)

            if exit_code == 0:
                try:
                    self.commit_changes(task_id)
                except Exception as exc:
                    self._log.warning(f"Git commit failed for {task_id}: {exc}")
            else:
                self._log.warning(f"Task {task_id} exited with code {exit_code} — skipping git commit")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vault Knowledge Factory — agent runtime",
    )
    parser.add_argument("--once", action="store_true", help="Run one scheduling cycle then exit")
    parser.add_argument("--task", metavar="TASK_ID", default=None, help="Run only this specific task")
    parser.add_argument(
        "--interval", type=int, default=_DEFAULT_INTERVAL, metavar="SECONDS",
        help=f"Poll interval between cycles (default: {_DEFAULT_INTERVAL}s)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    log = _Logger("runtime")

    if not _acquire_lock(log):
        sys.exit(1)

    try:
        t0 = log.start()
        runtime = Runtime()

        if args.once or args.task:
            runtime.run_cycle(task_filter=args.task)
            log.done(t0)
        else:
            log.info(f"Entering scheduler loop (interval={args.interval}s)")
            while True:
                try:
                    runtime.run_cycle()
                except Exception as exc:
                    log.error(f"Cycle error: {exc}")
                time.sleep(args.interval)
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
