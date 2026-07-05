"""runtime.tools.runner

Python runtime — the only static code in the agent pipeline.
Discovers agents from agent.json files, checks intervals, dispatches Claude agents.

CLI: python runner.py [--once] [--task TASK_ID] [--interval SECONDS]
     python runner.py --chat-id <uuid>   # dispatch one chat queue item
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid as _uuid_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# agents/ must be on sys.path so `import shared` resolves
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
from shared.loaders import load_registry  # noqa: E402
from shared.models import LmStudioConfig, RunResult  # noqa: E402
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

_SYSTEM_STATE  = _PROJECT_ROOT / "system" / "state"
_CHAT_QUEUE    = _SYSTEM_STATE / "chat-queue.json"
_INBOX_QUEUE   = _SYSTEM_STATE / "inbox-queue.json"
_VAULT_ROOT    = _PROJECT_ROOT / ".knowledge-base"

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}

# Maps dashboard agent name → task_id used in agent.json
_AGENT_NAME_TO_TASK: dict[str, str] = {
    "lore":           "lore-agent",
    "wiki":           "wiki-agent",
    "classification": "classification-agent",
    "vision":         "vision-agent",
    "ingestion":      "ingestion-agent",
    "repair":         "repair-agent",
    "review":         "review-agent",
}
_MAX_METRICS_RUNS   = 100

# Parses itemsProcessed / itemsFailed from agent DONE lines.
# Handles both runner format (processed=N) and shared.Logger format (classified: N).
# Spec keywords: classified|enriched|repairs|processed|converted|generated|linked
_DONE_PARSE_RE = re.compile(
    r"(?:classified|enriched|repairs|processed|converted|generated|linked)"
    r"[=:\s]+(\d+)"
    r".*?"
    r"(?:failed|failures)[=:\s]+(\d+)",
    re.IGNORECASE,
)

# Maps dispatch.type → attribute name on AgentDispatchConfig
_DISPATCH_TYPE_FIELD: dict[str, str] = {
    "cli":            "cli",
    "openai-api":     "openai_api",
    "claude-api":     "claude_api",
    "gemini-api":     "gemini_api",
    "openrouter-api": "openrouter_api",
    "claude-code":    "claude_code",
    "lm-studio":      "lm_studio",
    "codex-cli":      "codex_cli",
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
        self._write("INFO", f"--- DONE (processed: {count}, failed: {failed}, elapsed: {elapsed}s) ---")


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
        # Strip BOM: Windows PS may write UTF-8-BOM to agent-metrics.json
        text = _METRICS_JSON.read_text(encoding="utf-8").lstrip("﻿")
        return json.loads(text)
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
        # Log timestamps are local time (datetime.now()), so convert UTC 'after' to local
        ts_after = after.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        for line in _MASTER_LOG.read_text(encoding="utf-8").splitlines():
            if tag not in line or "--- DONE" not in line:
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
# Task discovery — reads agent.json files, respects execution_order
# ---------------------------------------------------------------------------

def _load_execution_order() -> list[str]:
    """Load execution_order list from registry.yaml. Returns [] on any error."""
    registry = _AGENTS_DIR / "registry.yaml"
    if not registry.exists():
        return []
    try:
        from ruamel.yaml import YAML  # available via requirements.txt
        data = YAML().load(registry.read_text(encoding="utf-8"))
        return list(data.get("execution_order", []))
    except Exception:
        return []


def _discover_tasks() -> list[tuple[str, TaskDispatchEntry]]:
    """Scan agents/*/agent.json and return all (task_id, TaskDispatchEntry) pairs.

    Tasks are ordered by execution_order from registry.yaml. Agents absent from
    execution_order are appended after all ordered agents, sorted alphabetically.
    """
    result: list[tuple[str, TaskDispatchEntry]] = []
    for agent_json in _AGENTS_DIR.glob("*/agent.json"):
        try:
            raw = json.loads(agent_json.read_text(encoding="utf-8"))
            folder = AgentFolderConfig.model_validate(raw)
            for task_id, entry in folder.tasks.items():
                result.append((task_id, entry))
        except Exception as exc:
            _Logger().warning(f"Skipping {agent_json}: {exc}")

    order = _load_execution_order()
    if order:
        def _sort_key(item: tuple[str, TaskDispatchEntry]) -> tuple[int, str]:
            agent_name = _agent_name_from_task_id(item[0])
            try:
                return (order.index(agent_name), item[0])
            except ValueError:
                return (len(order), item[0])  # unlisted agents last
        result.sort(key=_sort_key)
    else:
        result.sort(key=lambda t: t[0])  # stable fallback: alphabetical by task_id

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
    """Load and return the AgentDispatchConfig for task_id from agent.json.

    Falls back to registry.yaml's `default_dispatch` (paired with the
    agent's registered `tools:` entry) when agent.json is missing or has no
    entry for this task_id — lets an agent run off its registry.yaml
    declaration alone. See docs/specs/agents/agent-dispatch-settings.md.
    """
    agent_name = _agent_name_from_task_id(task_id)
    agent_json = _AGENTS_DIR / agent_name / "agent.json"

    if agent_json.exists():
        try:
            raw = json.loads(agent_json.read_text(encoding="utf-8"))
            folder_cfg = AgentFolderConfig.model_validate(raw)
        except Exception as exc:
            log.error(f"Failed to parse {agent_json}: {exc} — skipping {task_id}")
            return None

        entry: Optional[TaskDispatchEntry] = folder_cfg.tasks.get(task_id)
        if entry is not None:
            return entry.dispatch
        log.warning(f"Task ID {task_id!r} not found in {agent_json} — trying registry default_dispatch")
    else:
        log.warning(f"agent.json not found: {agent_json} — trying registry default_dispatch")

    return _build_default_dispatch(agent_name, task_id, log)


def _build_default_dispatch(agent_name: str, task_id: str, log: _Logger) -> Optional[AgentDispatchConfig]:
    """Build a fallback AgentDispatchConfig from registry.yaml's default_dispatch
    + the agent's `tools:` entry. Returns None if either is unavailable."""
    try:
        registry = load_registry(_PROJECT_ROOT)
    except Exception as exc:
        log.error(f"Could not load registry.yaml for default_dispatch fallback: {exc} — skipping {task_id}")
        return None

    default_cfg = registry.default_dispatch
    reg_agent   = registry.agents.get(agent_name)
    if default_cfg is None or reg_agent is None or not reg_agent.tools:
        log.error(
            f"No agent.json and no usable registry default for {task_id!r} "
            f"(agent={agent_name!r}) — skipping"
        )
        return None

    tool_path    = reg_agent.tools[0]                       # e.g. "tools/ingestion_agent.py"
    tool_stem    = Path(tool_path).stem                     # "ingestion_agent"
    tools_module = f"{agent_name}.tools.{tool_stem}"

    log.warning(
        f"Using registry default_dispatch for {task_id!r}: "
        f"type={default_cfg.type} model={default_cfg.model} tools_module={tools_module}"
    )

    if default_cfg.type != "lm-studio":
        log.error(f"default_dispatch type {default_cfg.type!r} not supported by fallback builder — skipping {task_id}")
        return None

    return AgentDispatchConfig(
        type=default_cfg.type,
        lm_studio=LmStudioConfig(
            base_url=default_cfg.base_url,
            model=default_cfg.model,
            timeout_seconds=default_cfg.timeout_seconds,
            system_file=default_cfg.system_file,
            tools_module=tools_module,
        ),
    )


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

        if exit_code != 0 and entry.fallback_dispatch is not None:
            log.info(f"Primary failed (exit {exit_code}) — trying fallback dispatch ({entry.fallback_dispatch.type})")
            try:
                fb_sub    = _extract_dispatch_sub(entry.fallback_dispatch)
                fb_runner = get_runner(entry.fallback_dispatch.type)
                log.info(f"Fallback via {entry.fallback_dispatch.type}: {fb_sub.get('tools_module', fb_sub.get('command', entry.fallback_dispatch.type))}")
                result    = fb_runner.run(fb_sub, context)
                exit_code = result.exit_code
                if result.error:
                    log.error(f"Fallback runner error: {result.error}")
            except Exception as exc:
                log.error(f"Fallback dispatch failed: {exc}")

        log.done(t0, count=1 if exit_code == 0 else 0, failed=0 if exit_code == 0 else 1)
        return exit_code, result

    def commit_changes(self, task_id: str) -> None:
        scope = _read_agent_commit_scope(task_id)
        if not scope:
            self._log.warning(
                f"No commit_scope declared for {task_id} — skipping git commit"
            )
            return

        # Clear the index first so any stray pre-staged file (leftover from a
        # prior partial run, manual `git add`, etc.) cannot leak into the auto
        # commit. After this, the index holds ONLY the scope paths staged below.
        subprocess.run(
            ["git", "reset", "-q"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
        )

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
            ["git", "commit", "-m", msg, "--", *scope],
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

    def run_cycle(self, task_filter: Optional[str] = None, force: bool = False) -> None:
        """One scheduling cycle: check all tasks, dispatch due and signal-triggered ones."""
        self.reload()
        _SIGNALS_DIR.mkdir(parents=True, exist_ok=True)

        signal_triggered = _check_signals(self._tasks, self._log)

        for task_id, entry in self._tasks:
            if task_filter and task_id != task_filter:
                continue

            if force:
                self._log.info(f"Force dispatch {task_id} (bypassing due/precondition checks)")
            else:
                due       = self.is_due(task_id)
                signalled = task_id in signal_triggered

                if not due and not signalled:
                    self._log.info(f"Skip {task_id} — not due, no signal")
                    continue

                # Precondition: skip if agent has no pending work (saves tokens)
                if not _check_preconditions(task_id, self._log):
                    continue

            # Pre-check: if agent.json is missing, skip without updating lastRun
            # (spec: agent.json missing → log error, skip, lastRun not updated)
            if _load_agent_dispatch(task_id, self._log) is None:
                continue

            reason = "force" if force else ("signalled" if signalled and not due else "due")
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
# Precondition checks — skip dispatch when agent has no work
# ---------------------------------------------------------------------------

def _read_inbox_queue() -> dict:
    if not _INBOX_QUEUE.exists():
        return {}
    try:
        return json.loads(_INBOX_QUEUE.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception:
        return {}


def _inbox_has_slot(slot: str) -> bool:
    """Return True if inbox-queue has at least one entry with agents.<slot> == 'pending'."""
    queue = _read_inbox_queue()
    for entry in queue.values():
        agents = entry.get("agents", {}) if isinstance(entry, dict) else {}
        if agents.get(slot) == "pending":
            return True
    return False


_CANON_VAULT_DIRS = frozenset({
    "00-Inbox", "01-Processing", "02-Library", "03-Campaigns",
    "04-Relationships", "05-Assets", "99-Archive",
})


def _vault_has_stray_entries() -> bool:
    """Return True if the vault root has top-level content outside the canonical folders.

    Ingestion's auto_absorb_stray step (agent-ingestion.spec.md) needs to run
    even when 00-Inbox itself is fully registered, so stray content still
    triggers dispatch instead of being skipped by the precondition check.
    """
    if not _VAULT_ROOT.exists():
        return False
    for entry in _VAULT_ROOT.iterdir():
        if entry.name in _CANON_VAULT_DIRS or entry.name.startswith("."):
            continue
        return True
    return False


def _inbox_has_new_files() -> bool:
    """Return True if 00-Inbox has any file not yet registered, or stray vault content exists."""
    if _vault_has_stray_entries():
        return True
    inbox = _VAULT_ROOT / "00-Inbox"
    if not inbox.exists():
        return False
    queue = _read_inbox_queue()
    for f in inbox.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(_PROJECT_ROOT).as_posix()
        if rel not in queue:
            return True
    return False


def _token_has_pending() -> bool:
    """Return True if any classified image lacks a generated token."""
    vision_state_path = _AGENTS_DIR / "vision" / "state" / "processed-images.json"
    gen_tokens_path   = _AGENTS_DIR / "token"  / "state" / "generated-tokens.json"
    try:
        vs = json.loads(vision_state_path.read_text(encoding="utf-8"))
        gt = json.loads(gen_tokens_path.read_text(encoding="utf-8")) if gen_tokens_path.exists() else {}
        images = vs.get("images", {})
        for img_key, entry in images.items():
            if (
                entry.get("status") == "ok"
                and not entry.get("isToken", False)
                and img_key not in gt
            ):
                return True
    except Exception:
        pass
    return False


def _wikilink_has_pending() -> bool:
    """Return True if 02-Library/ has files unprocessed or modified since last wikilink run."""
    library = _VAULT_ROOT / "02-Library"
    if not library.exists():
        return False
    state_path = _AGENTS_DIR / "wikilink" / "state" / "wikilink-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except Exception:
        state = {}
    for f in library.rglob("*.md"):
        rel = str(f.relative_to(_PROJECT_ROOT)).replace("\\", "/")
        if rel not in state:
            return True  # never processed
        try:
            processed_ts = datetime.fromisoformat(state[rel]["processedAt"]).timestamp()
            if f.stat().st_mtime > processed_ts:
                return True  # modified after last run
        except Exception:
            return True  # state corrupt → re-process
    return False


def _processing_has_files() -> bool:
    """Return True if 01-Processing/ has at least one .md file."""
    proc = _VAULT_ROOT / "01-Processing"
    if not proc.exists():
        return False
    return any(proc.rglob("*.md"))


def _has_old_logs(days: int = 7) -> bool:
    """Return True if log files older than `days` exist."""
    import time as _time
    cutoff = _time.time() - days * 86400
    logs_dir = _AGENTS_DIR / "runtime" / "state" / "logs"
    if not logs_dir.exists():
        return False
    for f in logs_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            return True
    return False


# Map task_id → precondition function (returns bool; True = has work, False = skip)
_PRECONDITIONS: dict[str, "Callable[[], bool]"] = {}

def _build_preconditions() -> None:
    """Populate _PRECONDITIONS after module-level paths are set."""
    _PRECONDITIONS.update({
        "ingestion-agent":              _inbox_has_new_files,
        "vision-agent":                 lambda: _inbox_has_slot("vision"),
        "lore-agent":                   lambda: _inbox_has_slot("lore"),
        "classification-agent":         lambda: _inbox_has_slot("classification"),
        "wiki-agent":                   lambda: _inbox_has_slot("wiki"),
        "token-agent":                  _token_has_pending,
        "wikilink-agent":               _wikilink_has_pending,
        "review-agent-short-files":     _processing_has_files,
        "cleanup-agent":                lambda: _has_old_logs(days=7),
        # review-agent and repair-agent always run (health monitors)
    })

_build_preconditions()


def _check_preconditions(task_id: str, log: _Logger) -> bool:
    """Return True if task has work. False = skip (no tokens consumed)."""
    check = _PRECONDITIONS.get(task_id)
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


# ---------------------------------------------------------------------------
# Chat queue dispatch
# ---------------------------------------------------------------------------

def _read_chat_queue() -> list[dict]:
    if not _CHAT_QUEUE.exists():
        return []
    try:
        data = json.loads(_CHAT_QUEUE.read_text(encoding="utf-8").lstrip("﻿"))
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_chat_queue(items: list[dict]) -> None:
    _SYSTEM_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _CHAT_QUEUE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    tmp.replace(_CHAT_QUEUE)


def _chat_update(items: list[dict], chat_id: str, **fields) -> None:
    for item in items:
        if item.get("id") == chat_id:
            item.update(fields)
            item["updatedAt"] = datetime.now(timezone.utc).isoformat()
            break


def _load_system_prompt(agent_name: str) -> str:
    candidates = [
        _AGENTS_DIR / agent_name / "prompts" / "system.md",
        _AGENTS_DIR / agent_name / "prompts" / "system.txt",
    ]
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return (
        "You are a Dungeon Master knowledge assistant for a tabletop RPG campaign. "
        "Help with worldbuilding, NPC creation, locations, quests, factions, lore, and narrative. "
        "Be concise, creative, and specific."
    )


def _call_lm_studio(cfg: dict, system: str, user_message: str) -> str:
    """Send chat message to LM Studio (OpenAI-compatible) endpoint."""
    base_url   = cfg["base_url"].rstrip("/")
    url        = f"{base_url}/chat/completions"
    timeout_s  = int(cfg.get("timeout_seconds", 120))
    payload    = {
        "model":       cfg["model"],
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_message},
        ],
        "temperature": float(cfg.get("temperature", 0.0)),
        "max_tokens":  int(cfg.get("max_tokens", 2048)),
        "stream":      False,
    }
    body    = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer lm-studio"}
    req     = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _call_claude(cfg: dict, system: str, user_message: str) -> str:
    """Send chat message to Anthropic Claude API."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client   = anthropic.Anthropic(api_key=api_key, timeout=float(cfg.get("timeout_seconds", 120)))
    response = client.messages.create(
        model=cfg.get("model", "claude-haiku-4-5-20251001"),
        max_tokens=int(cfg.get("max_tokens", 2048)),
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(
        block.text for block in response.content if block.type == "text"
    )


def _dispatch_chat(chat_id: str) -> int:
    """Dispatch a single chat queue item by ID. Returns exit code."""
    log = _Logger("chat")

    items = _read_chat_queue()
    item  = next((i for i in items if i.get("id") == chat_id), None)
    if item is None:
        log.error(f"Chat item {chat_id!r} not found in queue")
        return 1

    agent_name  = item.get("agentName", "")
    user_message = item.get("message", "")
    task_id     = _AGENT_NAME_TO_TASK.get(agent_name, f"{agent_name}-agent")

    _chat_update(items, chat_id, status="processing")
    _write_chat_queue(items)

    log.info(f"Chat dispatch: agent={agent_name} task={task_id} id={chat_id}")

    try:
        dispatch_cfg = _load_agent_dispatch(task_id, log)
        if dispatch_cfg is None:
            raise RuntimeError(f"Cannot load dispatch config for task {task_id!r}")

        sub = _extract_dispatch_sub(dispatch_cfg)
        system = _load_system_prompt(agent_name)
        dispatch_type = dispatch_cfg.type

        if dispatch_type in ("lm-studio", "openai-api"):
            response = _call_lm_studio(sub, system, user_message)
        elif dispatch_type == "claude-api":
            response = _call_claude(sub, system, user_message)
        else:
            raise RuntimeError(f"Unsupported dispatch type for chat: {dispatch_type!r}")

        _chat_update(items, chat_id, status="done", response=response)
        _write_chat_queue(items)
        log.info(f"Chat done: {chat_id}")
        return 0

    except Exception as exc:
        log.error(f"Chat dispatch failed: {exc}")
        _chat_update(items, chat_id, status="error", error=str(exc))
        _write_chat_queue(items)
        return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vault Nexus Campaigns — agent runtime",
    )
    parser.add_argument("--once", action="store_true", help="Run one scheduling cycle then exit")
    parser.add_argument("--task", metavar="TASK_ID", default=None, help="Run only this specific task")
    parser.add_argument("--chat-id", metavar="UUID", default=None, help="Dispatch one chat queue item by ID then exit")
    parser.add_argument("--force", action="store_true", help="Bypass due-time and precondition checks (for testing)")
    parser.add_argument(
        "--interval", type=int, default=_DEFAULT_INTERVAL, metavar="SECONDS",
        help=f"Poll interval between cycles (default: {_DEFAULT_INTERVAL}s)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    log = _Logger("runtime")

    if args.chat_id:
        sys.exit(_dispatch_chat(args.chat_id))

    if not _acquire_lock(log):
        sys.exit(1)

    try:
        t0 = log.start()
        runtime = Runtime()

        if args.once or args.task:
            runtime.run_cycle(task_filter=args.task, force=args.force)
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
