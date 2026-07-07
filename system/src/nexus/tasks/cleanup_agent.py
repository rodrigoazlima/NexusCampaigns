"""nexus.tasks.cleanup_agent

Cleanup task — log/report rotation and metrics trimming.
  - Purge log files older than CLEANUP_DAYS (90)
  - Purge report files older than CLEANUP_DAYS
  - Trim agent-metrics.json run history to last 100 entries per agent
  - Write CleanupReport to system/state/cleanup/reports/cleanup-{YYYY-MM-DD}.json

No LLM. No vault content changes.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from nexus.shared.logger import Logger
from nexus.shared.loaders import _find_project_root

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

TASK_ID         = "cleanup-agent"
SCRIPT_BASENAME = "cleanup_agent.py"
MAX_METRIC_RUNS = 100
# ponytail: fixed retention — registry-level override if a need ever shows up
CLEANUP_DAYS    = 90

_AGENTS_DIR   = _PROJECT_ROOT / "agents"
_STATE_ROOT   = _PROJECT_ROOT / "system" / "state"
_AGENT_STATE  = _STATE_ROOT / "cleanup"
_LOGS_DIR     = _AGENT_STATE / "logs"
_REPORTS_DIR  = _AGENT_STATE / "reports"
_MASTER_LOG   = _STATE_ROOT / "runtime" / "logs" / "automation.log"
_METRICS_FILE = _STATE_ROOT / "runtime" / "agent-metrics.json"


def _make_logger() -> Logger:
    return Logger(
        task_id        = TASK_ID,
        script_basename= SCRIPT_BASENAME,
        logs_dir       = _LOGS_DIR,
        master_log     = _MASTER_LOG,
    )


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

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
    """Purge log files older than keep_days across all task/agent log directories."""
    total = 0
    for logs_dir in (*_AGENTS_DIR.glob("*/state/logs"), *_STATE_ROOT.glob("*/logs")):
        total += _purge_dir(logs_dir, keep_days, log)
    return total


def purge_reports(keep_days: int, log: Logger) -> int:
    """Purge report files older than keep_days across all task/agent report directories."""
    total = 0
    for reports_dir in (*_AGENTS_DIR.glob("*/state/reports"), *_STATE_ROOT.glob("*/reports")):
        total += _purge_dir(reports_dir, keep_days, log)
    return total


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
    """Write CleanupReport to state/reports/cleanup-{date}.json atomically."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report = {
        "date":           today,
        "generatedAt":    datetime.now(timezone.utc).isoformat(),
        "logsDeleted":    logs_deleted,
        "reportsDeleted": reports_deleted,
        "metricsTrimmed": metrics_trimmed,
    }
    out = _REPORTS_DIR / f"cleanup-{today}.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(out)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log = _make_logger()
    t0  = log.start()

    logs_deleted    = purge_logs(CLEANUP_DAYS, log)
    reports_deleted = purge_reports(CLEANUP_DAYS, log)
    metrics_trimmed = trim_metrics(MAX_METRIC_RUNS, log)

    _write_report(logs_deleted, reports_deleted, metrics_trimmed)

    total = logs_deleted + reports_deleted + metrics_trimmed
    log.done(t0, key="processed", count=total, failed=0)
    sys.exit(0)


if __name__ == "__main__":
    main()
