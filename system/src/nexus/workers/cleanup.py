"""nexus.workers.cleanup - scheduled housekeeping worker.

Purges log/report files older than retention_days, trims agent-metrics.json
run history, writes a CleanupReport. Replaces nexus.tasks.cleanup_agent.
No LLM. No vault content changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from nexus.shared.loaders import _find_project_root
from nexus.shared.logger import Logger
from nexus.workers.base import WORKERS_STATE_ROOT, WorkItem, WorkResult, make_worker_logger

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

MAX_METRIC_RUNS = 100

_AGENTS_DIR   = _PROJECT_ROOT / "agents"
_STATE_ROOT   = _PROJECT_ROOT / "system" / "state"
_WORKERS_ROOT = _STATE_ROOT / "workers"
_METRICS_FILE = _AGENTS_DIR / "runtime" / "state" / "agent-metrics.json"
_REPORTS_DIR  = WORKERS_STATE_ROOT / "cleanup" / "reports"


def _scan_dirs(sub: str) -> list[Path]:
    """All log/report directories across runtime, LLM agents, and workers.

    Tracks the state layout, which is code's business - not config.
    """
    return [
        *_AGENTS_DIR.glob(f"*/state/{sub}"),      # LLM agents + runtime
        *_STATE_ROOT.glob(f"*/{sub}"),            # legacy system/state/<x>/logs
        *_WORKERS_ROOT.glob(f"*/{sub}"),          # system/state/workers/<name>/logs
    ]


def _purge_dir(directory: Path, keep_days: int, log: Logger) -> int:
    """Delete files in directory older than keep_days. Returns count deleted."""
    if not directory.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    deleted = 0
    for f in directory.iterdir():
        if not f.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                age = (datetime.now(timezone.utc) - mtime).days
                log.info(f"Purged: {f.name} (age={age}d)")
                deleted += 1
        except Exception as exc:
            log.warning(f"Could not delete {f.name}: {exc}")
    return deleted


def purge_logs(keep_days: int, log: Logger) -> int:
    return sum(_purge_dir(d, keep_days, log) for d in _scan_dirs("logs"))


def purge_reports(keep_days: int, log: Logger) -> int:
    return sum(_purge_dir(d, keep_days, log) for d in _scan_dirs("reports"))


def trim_metrics(max_runs: int, log: Logger) -> int:
    """Trim agent-metrics.json to max_runs entries per agent. Returns total runs removed."""
    if not _METRICS_FILE.exists():
        return 0
    try:
        raw = _METRICS_FILE.read_text(encoding="utf-8").lstrip("﻿")
        data: dict = json.loads(raw)
    except Exception as exc:
        log.error(f"Could not read agent-metrics.json: {exc}")
        return 0

    removed = 0
    for agent_id, entry in data.items():
        runs = entry.get("runs", [])
        if len(runs) > max_runs:
            trimmed = len(runs) - max_runs
            entry["runs"] = runs[-max_runs:]
            removed += trimmed
            log.info(f"Trimmed {trimmed} old run(s) from {agent_id}")

    if removed:
        tmp = _METRICS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_METRICS_FILE)

    return removed


def _write_report(logs_deleted: int, reports_deleted: int, metrics_trimmed: int) -> None:
    reports_dir = _REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report = {
        "date":           today,
        "generatedAt":    datetime.now(timezone.utc).isoformat(),
        "logsDeleted":    logs_deleted,
        "reportsDeleted": reports_deleted,
        "metricsTrimmed": metrics_trimmed,
    }
    out = reports_dir / f"cleanup-{today}.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(out)


class CleanupWorker:
    name = "cleanup"
    kind = "scheduled"

    def __init__(self, options: dict | None = None) -> None:
        opts = options or {}
        self.retention_days = int(opts.get("retention_days", 90))

    def pending(self) -> list[WorkItem]:
        return [WorkItem("", {})]

    def handle(self, item: WorkItem) -> WorkResult:
        log = make_worker_logger(self.name)
        t0 = log.start()

        logs_deleted    = purge_logs(self.retention_days, log)
        reports_deleted = purge_reports(self.retention_days, log)
        metrics_trimmed = trim_metrics(MAX_METRIC_RUNS, log)

        total = logs_deleted + reports_deleted + metrics_trimmed
        if total == 0:
            log.done(t0, key="processed", count=0, failed=0)
            return WorkResult("skip", "nothing old enough")

        _write_report(logs_deleted, reports_deleted, metrics_trimmed)
        log.done(t0, key="processed", count=total, failed=0)
        return WorkResult(
            "done",
            f"logs={logs_deleted} reports={reports_deleted} metricsTrimmed={metrics_trimmed}",
        )


def create(options: dict | None = None) -> CleanupWorker:
    return CleanupWorker(options)


if __name__ == "__main__":
    worker = create()
    for _item in worker.pending():
        _res = worker.handle(_item)
        print(f"{_res.status}: {_res.detail}")
