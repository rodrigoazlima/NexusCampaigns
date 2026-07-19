"""nexus.runtime.scheduler - Runtime, the IOrchestrator implementation.

Discovers agents from agent.json files and runs one scheduling cycle: checks
due-time/signals/preconditions, dispatches agents (sync or concurrently per
registry.yaml's pipeline_mode), records their metrics/cost/commit, then hands
off to the worker loop for in-process static work.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from nexus.shared import (
    AgentDispatchConfig,
    DispatchError,
    FileLock,
    IOrchestrator,
    TasksState,
    TaskStateEntry,
    TaskDispatchEntry,
    get_runner,
)
from nexus.shared.models import RunResult
from nexus.shared.signal_bus import SignalConsumer

from . import dispatch_config, worker_loop
from .committer import commit_scoped
from .costs import record_cost
from .discovery import discover_tasks
from .log import make_logger
from .metrics import parse_agent_items, record_metrics
from .paths import MASTER_LOG, PROJECT_ROOT, STATE_JSON, AGENTS_DIR, SIGNALS_DIR
from .preconditions import check_preconditions
from .registry_yaml import load_pipeline_mode
from .signals import check_signals
from .state import load_state, save_state


class Runtime(IOrchestrator):
    """Discovers agents from agent.json files, schedules and dispatches them."""

    def __init__(self) -> None:
        self._tasks: list[tuple[str, TaskDispatchEntry]] = []
        self._state: Optional[TasksState] = None
        self._log = make_logger("runtime")

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
        return dispatch_config.load_agent_dispatch(task_id, self._log)

    def dispatch(self, task_id: str) -> tuple[int, RunResult]:
        entry = self._get_task_entry(task_id)
        _empty = RunResult(exit_code=1)
        if entry is None:
            self._log.error(f"Task not found in any agent.json: {task_id}")
            return 1, _empty

        agent_name = dispatch_config.agent_name_from_task_id(task_id)
        if dispatch_config.agent_is_sandboxed(agent_name) and not dispatch_config.running_inside_sandbox():
            return self._dispatch_sandboxed(agent_name, task_id)

        dispatch_cfg = dispatch_config.load_agent_dispatch(task_id, self._log)
        if dispatch_cfg is None:
            return 1, _empty

        log = make_logger(task_id)
        t0 = log.start()
        exit_code = 1
        result = _empty

        try:
            sub_config = dispatch_config.extract_dispatch_sub(dispatch_cfg)
            runner = get_runner(dispatch_cfg.type)
            agent_name = dispatch_config.agent_name_from_task_id(task_id)
            context = {
                "project_root": str(PROJECT_ROOT),
                "agents_dir":   str(AGENTS_DIR),
                "agent_dir":    str(AGENTS_DIR / agent_name),
                "task_id":      task_id,
                "master_log":   str(MASTER_LOG),
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
            log.info(f"Primary failed (exit {exit_code}) - trying fallback dispatch ({entry.fallback_dispatch.type})")
            try:
                fb_sub    = dispatch_config.extract_dispatch_sub(entry.fallback_dispatch)
                fb_runner = get_runner(entry.fallback_dispatch.type)
                log.info(f"Fallback via {entry.fallback_dispatch.type}: {fb_sub.get('tools_module', fb_sub.get('command', entry.fallback_dispatch.type))}")
                result    = fb_runner.run(fb_sub, context)
                exit_code = result.exit_code
                if result.error:
                    log.error(f"Fallback runner error: {result.error}")
            except Exception as exc:
                log.error(f"Fallback dispatch failed: {exc}")

        log.done(t0, key="processed", count=1 if exit_code == 0 else 0, failed=0 if exit_code == 0 else 1)
        return exit_code, result

    def _dispatch_sandboxed(self, agent_name: str, task_id: str) -> tuple[int, RunResult]:
        """Run this task via nexus.tasks.sandbox_run instead of the normal
        get_runner() path - registry.yaml's agents.<name>.sandbox.enabled.

        sandbox_run.run() already applies knowledge-base/state changes
        straight to their real host paths and forwards the container's own
        automation.log lines onto ours (so metrics parsing below still
        works); commit_changes() afterward is unaffected - it commits
        whatever landed at the real commit_scope paths either way.
        """
        log = make_logger(task_id)
        t0 = log.start()
        log.info(f"Sandboxed dispatch: routing {task_id} through nexus.tasks.sandbox_run")
        try:
            from nexus.tasks import sandbox_run  # lazy: pulls in the full runtime/shared stack
            exit_code = sandbox_run.run(agent_name)
        except Exception as exc:
            log.error(f"Sandboxed dispatch failed: {exc}")
            exit_code = 1
        result = RunResult(exit_code=exit_code, duration_ms=int((time.monotonic() - t0) * 1000))
        log.done(t0, key="processed", count=1 if exit_code == 0 else 0, failed=0 if exit_code == 0 else 1)
        return exit_code, result

    def commit_changes(self, task_id: str) -> None:
        if dispatch_config.running_inside_sandbox():
            # This container copy has no .git (and no git binary) - it's
            # discarded on cleanup regardless. The host-side
            # _dispatch_sandboxed() caller commits the real repo after
            # extracting applied changes; committing here would only ever
            # fail with a doomed FileNotFoundError.
            return
        scope = dispatch_config.read_agent_commit_scope(task_id)
        if not scope:
            self._log.warning(
                f"No commit_scope declared for {task_id} - skipping git commit"
            )
            return
        commit_scoped(task_id, scope, self._log)

    # Internals -------------------------------------------------------------

    def _get_task_entry(self, task_id: str) -> Optional[TaskDispatchEntry]:
        for tid, entry in self._tasks:
            if tid == task_id:
                return entry
        return None

    def reload(self) -> None:
        """Discover tasks from agent.json files and reload run state."""
        self._tasks = discover_tasks()
        self._state = load_state()
        self._log.info(f"Discovered {len(self._tasks)} tasks from agent.json files")

    def _run_one(self, task_id: str, entry: TaskDispatchEntry, reason: str) -> None:
        """Dispatch a single task and record its state/metrics/cost/commit.

        Safe to call from multiple threads concurrently (pipeline_mode: async):
        state-file writes and git commits are each serialized via FileLock.
        """
        self._log.info(f"Dispatching {task_id} ({entry.description}) [{reason}]")
        started_at  = datetime.now(timezone.utc)
        exit_code, result = self.dispatch(task_id)
        finished_at = datetime.now(timezone.utc)

        assert self._state is not None
        self._state[task_id] = TaskStateEntry(lastRun=finished_at)
        with FileLock(STATE_JSON, timeout=30.0):
            save_state(self._state)

        try:
            processed, failed = parse_agent_items(task_id, started_at)
            record_metrics(task_id, started_at, finished_at, processed, failed)
        except Exception as exc:
            self._log.warning(f"Metrics update failed for {task_id}: {exc}")

        try:
            record_cost(
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
            self._log.warning(f"Task {task_id} exited with code {exit_code} - skipping git commit")

    def run_cycle(self, task_filter: Optional[str] = None, force: bool = False) -> None:
        """One scheduling cycle: check all tasks, dispatch due and signal-triggered ones.

        pipeline_mode (registry.yaml) controls dispatch order:
          sync  - one agent at a time, in execution_order (default)
          async - all due/signalled agents for this cycle run concurrently

        task_filter "worker:<name>" runs only that worker (no agent dispatch).
        """
        self.reload()
        SIGNALS_DIR.mkdir(parents=True, exist_ok=True)

        worker_filter: Optional[str] = None
        if task_filter and task_filter.startswith("worker:"):
            worker_filter = task_filter.split(":", 1)[1]

        signal_triggered = check_signals(self._tasks, self._log)

        to_run: list[tuple[str, TaskDispatchEntry, str]] = []
        for task_id, entry in self._tasks:
            if worker_filter or (task_filter and task_id != task_filter):
                continue

            if force:
                self._log.info(f"Force dispatch {task_id} (bypassing due/precondition checks)")
                reason = "force"
            else:
                due       = self.is_due(task_id)
                signalled = task_id in signal_triggered

                if not due and not signalled:
                    self._log.info(f"Skip {task_id} - not due, no signal")
                    continue

                # Precondition: skip if agent has no pending work (saves tokens)
                if not check_preconditions(task_id, self._log):
                    continue

                reason = "signalled" if signalled and not due else "due"

            # Pre-check: if agent.json is missing, skip without updating lastRun
            # (spec: agent.json missing → log error, skip, lastRun not updated)
            if dispatch_config.load_agent_dispatch(task_id, self._log) is None:
                continue

            to_run.append((task_id, entry, reason))

        pipeline_mode = load_pipeline_mode()
        if pipeline_mode == "async" and len(to_run) > 1:
            self._log.info(f"pipeline_mode=async - dispatching {len(to_run)} task(s) concurrently")
            from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
            with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
                futures = [pool.submit(self._run_one, tid, e, r) for tid, e, r in to_run]
                for fut in futures:
                    fut.result()
        else:
            for task_id, entry, reason in to_run:
                self._run_one(task_id, entry, reason)

        # Consume processed signals AFTER all dispatches in this cycle
        consumer = SignalConsumer(SIGNALS_DIR)
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

        # Worker loop - in-process static workers (worker-contract.spec.md).
        # Skipped when a specific agent task was requested via --task.
        if task_filter is None or worker_filter is not None:
            assert self._state is not None
            worker_loop.run_workers(self._state, self._log, worker_filter=worker_filter, force=force)
