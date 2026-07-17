"""nexus.runtime.worker_loop — runs the in-process static workers
(worker-contract.spec.md) after each agent-dispatch cycle: queue workers
poll every cycle, scheduled workers respect their own interval_seconds."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from nexus.shared import FileLock, Logger, TasksState, TaskStateEntry
from nexus.shared.signal_bus import SignalConsumer, SignalEmitter
from nexus.workers.base import WorkerConfig, create_worker, load_worker_configs, workers_enabled

from .committer import commit_scoped
from .metrics import record_worker_metrics
from .paths import SIGNALS_DIR, STATE_JSON, WORKER_ERROR_SIGNAL
from .registry_yaml import load_registry_dict
from .state import save_state


def worker_due(cfg: WorkerConfig, state: TasksState) -> bool:
    """Scheduled workers run on interval_seconds; queue workers poll every cycle."""
    if cfg.kind != "scheduled":
        return True
    entry = state.get(f"worker:{cfg.name}")
    if entry is None:
        return True
    last = entry.lastRun
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() >= cfg.interval_seconds


def run_workers(
    state: TasksState,
    log: Logger,
    worker_filter: Optional[str] = None,
    force: bool = False,
) -> None:
    registry = load_registry_dict()
    if not workers_enabled(registry) and not force:
        return

    emitter  = SignalEmitter(SIGNALS_DIR)
    consumer = SignalConsumer(SIGNALS_DIR)

    for cfg in load_worker_configs(registry):
        if worker_filter and cfg.name != worker_filter:
            continue
        if not cfg.enabled and not force:
            continue

        # A worker-error signal forces the maintenance worker to run now
        # instead of waiting out its daily interval.
        signalled = (
            cfg.name == "maintenance"
            and bool(consumer.pending(WORKER_ERROR_SIGNAL))
        )
        if not force and not signalled and not worker_due(cfg, state):
            continue

        try:
            worker = create_worker(cfg)
        except Exception as exc:
            log.error(f"Worker '{cfg.name}' failed to load: {exc}")
            continue

        try:
            items = worker.pending()[: cfg.batch_size]
        except Exception as exc:
            log.warning(f"Worker '{cfg.name}' pending() failed: {exc} — treating as empty")
            items = []
        if not items:
            continue

        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
        processed = failed = done_count = 0
        for item in items:
            try:
                result = worker.handle(item)
            except Exception as exc:
                result = None
                failed += 1
                log.error(f"Worker '{cfg.name}' item {item.key!r} raised: {exc}")
                emitter.emit(WORKER_ERROR_SIGNAL, cfg.name, ref=item.key)
                continue
            if result.status == "error":
                failed += 1
                log.warning(f"Worker '{cfg.name}' item {item.key!r} error: {result.detail}")
                emitter.emit(WORKER_ERROR_SIGNAL, cfg.name, ref=item.key)
            else:
                processed += 1
                if result.status == "done":
                    done_count += 1

        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            f"Worker '{cfg.name}': processed={processed} failed={failed} ({duration_ms}ms)"
        )

        state[f"worker:{cfg.name}"] = TaskStateEntry(lastRun=datetime.now(timezone.utc))
        with FileLock(STATE_JSON, timeout=30.0):
            save_state(state)

        try:
            record_worker_metrics(cfg.name, started_at, processed, failed, duration_ms)
        except Exception as exc:
            log.warning(f"Metrics update failed for worker '{cfg.name}': {exc}")

        if done_count and cfg.commit_scope:
            try:
                commit_scoped(f"worker:{cfg.name}", cfg.commit_scope, log)
            except Exception as exc:
                log.warning(f"Git commit failed for worker '{cfg.name}': {exc}")

        if signalled:
            consumed = consumer.consume_all(WORKER_ERROR_SIGNAL)
            if consumed:
                log.info(
                    f"Consumed {len(consumed)} '{WORKER_ERROR_SIGNAL}' signal(s) for maintenance"
                )
