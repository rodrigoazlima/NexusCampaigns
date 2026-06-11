You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.shared/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.shared/config/<script_name>.json`)
     - Contains script-specific settings and overrides.
     - Always loaded after global config (can override global values).
     - Can be empty (`{}`) but must always exist.

2. **Output Format:**
   - You must output **two valid JSON objects** clearly labeled.
   - Use sensible, descriptive keys in `snake_case`.
   - Include meaningful `default` values for every setting.
   - Add a `"description"` field for each major setting when helpful.
   - Group related settings under logical sections if needed.

3. **What to Extract:**
   - Hardcoded paths (especially those derived from `__file__`)
   - Constants (BATCH_SIZE, thresholds, limits, etc.)
   - LLM settings (URL, model, provider, etc.)
   - File/directory references
   - Magic numbers and strings that are likely to change
   - Any environment-dependent behavior

4. **Rules:**
   - Prefer putting common things (project roots, LLM config, logging, shared directories) in **global**.
   - Put script-specific behavior (batch sizes, task-specific prompts, agent name, etc.) in **local**.
   - Make sure the JSONs contain good defaults so the script works even if the files are deleted.
   - Use clear, consistent naming.
   - Do not include code — only configuration.

---

**Script to analyze:**

# runtime\tools\runner.py
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
from shared.models import RunResult  # noqa: E402
from shared.signal_bus import SignalConsumer  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_RUNTIME_STATE = Path(__file__).resolve().parents[1] / "state"
_STATE_JSON    = _RUNTIME_STATE / "tasks-state.json"
_METRICS_JSON  = _RUNTIME_STATE / "agent-metrics.json"
_LOCK_FILE     = _RUNTIME_STATE / "runner.lock"
_LOGS_DIR      = _RUNTIME_STATE / "logs"
_MASTER_LOG    = _LOGS_DIR / "automation.log"
_SIGNALS_DIR   = _RUNTIME_STATE / "signals"
_COSTS_DIR     = _RUNTIME_STATE / "costs"

_LOCK_STALE_SECONDS = 1800   # 30 min
_DEFAULT_INTERVAL   = 60     # orchestrator poll cadence
_MAX_METRICS_RUNS   = 100

# Parses "processed=N failed=N" from agent DONE lines
_DONE_PARSE_RE = re.compile(r"processed=(\d+).*?failed=(\d+)")

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
# Metrics helpers
# ---------------------------------------------------------------------------

def _load_metrics() -> dict:
    if not _METRICS_JSON.exists():
        return {}
    try:
        return json.loads(_METRICS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_metrics(data: dict) -> None:
    tmp = _METRICS_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_METRICS_JSON)


def _parse_agent_items(task_id: str, after: datetime) -> tuple[int, int]:
    """Return (processed, failed) from the agent's first DONE line after 'after'."""
    if not _MASTER_LOG.exists():
        return 0, 0
    try:
        tag = f"[{task_id}]"
        ts_after = after.strftime("%Y-%m-%d %H:%M:%S")
        for line in _MASTER_LOG.read_text(encoding="utf-8").splitlines():
            if tag not in line or "--- DONE ---" not in line:
                continue
            ts_m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
            if ts_m and ts_m.group(1) >= ts_after:
                m = _DONE_PARSE_RE.search(line)
                if m:
                    return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 0, 0


def _record_metrics(
    task_id: str,
    started_at: datetime,
    finished_at: datetime,
    items_processed: int,
    items_failed: int,
) -> None:
    data = _load_metrics()
    entry = data.setdefault(task_id, {"runs": []})
    entry["runs"].append({
        "startedAt":      started_at.isoformat(),
        "finishedAt":     finished_at.isoformat(),
        "durationMs":     int((finished_at - started_at).total_seconds() * 1000),
        "itemsProcessed": items_processed,
        "itemsFailed":    items_failed,
    })
    if len(entry["runs"]) > _MAX_METRICS_RUNS:
        entry["runs"] = entry["runs"][-_MAX_METRICS_RUNS:]
    _save_metrics(data)


# ---------------------------------------------------------------------------
# Cost recording
# ---------------------------------------------------------------------------

def _record_cost(
    task_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    started_at: datetime,
) -> None:
    """Append per-run token usage to the daily cost file (atomic write)."""
    if not model and not input_tokens and not output_tokens:
        return  # non-Claude runner — nothing to record

    today = started_at.strftime("%Y-%m-%d")
    _COSTS_DIR.mkdir(parents=True, exist_ok=True)
    cost_file = _COSTS_DIR / f"costs-{today}.json"

    data: dict = {}
    if cost_file.exists():
        try:
            data = json.loads(cost_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    entry = data.setdefault(task_id, {"runs": []})
    entry["runs"].append({
        "ts":            started_at.isoformat(),
        "model":         model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
    })

    tmp = cost_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(cost_file)


# ---------------------------------------------------------------------------
# Signal bus helpers
# ---------------------------------------------------------------------------

def _check_signals(
    tasks: list[tuple[str, TaskDispatchEntry]],
    log: _Logger,
) -> set[str]:
    """Return task_ids that should run immediately due to pending signals."""
    consumer = SignalConsumer(_SIGNALS_DIR)
    triggered: set[str] = set()

    for task_id, entry in tasks:
        triggers = list(getattr(entry, "signal_triggers", None) or [])
        for signal_type in triggers:
            pending = consumer.pending(signal_type)
            if pending:
                log.info(
                    f"Signal '{signal_type}' pending ({len(pending)} item(s)) — "
                    f"triggering {task_id} immediately"
                )
                triggered.add(task_id)
                break

    return triggered


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

    def dispatch(self, task_id: str) -> tuple[int, RunResult]:
        entry = self._get_task_entry(task_id)
        _empty = RunResult(exit_code=1)
        if entry is None:
            self._log.error(f"Task not found in any agent.json: {task_id}")
            return 1, _empty

        dispatch_cfg = _load_agent_dispatch(task_id, self._log)
        if dispatch_cfg is None:
            return 1, _empty

        log = _Logger(task_id)
        t0 = log.start()
        exit_code = 1
        result = _empty

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
        return exit_code, result

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
        """One scheduling cycle: check all tasks, dispatch due and signal-triggered ones."""
        self.reload()
        _SIGNALS_DIR.mkdir(parents=True, exist_ok=True)

        signal_triggered = _check_signals(self._tasks, self._log)

        for task_id, entry in self._tasks:
            if task_filter and task_id != task_filter:
                continue

            due       = self.is_due(task_id)
            signalled = task_id in signal_triggered

            if not due and not signalled:
                self._log.info(f"Skip {task_id} — not due, no signal")
                continue

            reason = "signalled" if signalled and not due else "due"
            self._log.info(f"Dispatching {task_id} ({entry.description}) [{reason}]")
            started_at  = datetime.now(timezone.utc)
            exit_code, result = self.dispatch(task_id)
            finished_at = datetime.now(timezone.utc)

            assert self._state is not None
            self._state[task_id] = TaskStateEntry(lastRun=finished_at)
            _save_state(self._state)

            try:
                processed, failed = _parse_agent_items(task_id, started_at)
                _record_metrics(task_id, started_at, finished_at, processed, failed)
            except Exception as exc:
                self._log.warning(f"Metrics update failed for {task_id}: {exc}")

            try:
                _record_cost(
                    task_id,
                    result.model,
                    result.input_tokens,
                    result.output_tokens,
                    started_at,
                )
            except Exception as exc:
                self._log.warning(f"Cost recording failed for {task_id}: {exc}")

            if exit_code == 0:
                try:
                    self.commit_changes(task_id)
                except Exception as exc:
                    self._log.warning(f"Git commit failed for {task_id}: {exc}")
            else:
                self._log.warning(f"Task {task_id} exited with code {exit_code} — skipping git commit")

        # Consume processed signals AFTER all dispatches in this cycle
        consumer = SignalConsumer(_SIGNALS_DIR)
        for task_id in signal_triggered:
            entry = self._get_task_entry(task_id)
            if entry is None:
                continue
            triggers = list(getattr(entry, "signal_triggers", None) or [])
            for signal_type in triggers:
                consumed = consumer.consume_all(signal_type)
                if consumed:
                    self._log.info(
                        f"Consumed {len(consumed)} '{signal_type}' signal(s) for {task_id}"
                    )


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


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .shared/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```

### Bonus: Loader Code Suggestion (for `shared/config.py`)

You can later create a simple loader like this:

```python
from pathlib import Path
import json

def load_config(script_path: Path):
    project_root = Path(__file__).resolve().parents[2]  # adjust as needed
    
    # Global
    global_path = project_root / "config" / "global.json"
    global_cfg = json.loads(global_path.read_text()) if global_path.exists() else {}
    
    # Local
    script_name = script_path.stem
    local_path = project_root / "config" / f"{script_name}.json"
    local_cfg = json.loads(local_path.read_text()) if local_path.exists() else {}
    
    # Merge (local overrides global)
    config = {**global_cfg, **local_cfg}
    return config
```

