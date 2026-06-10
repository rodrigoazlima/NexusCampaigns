"""cleanup.tools.cleanup_agent

Cleanup Agent — log/report rotation and metrics trimming.
  - Purge log files older than cleanupDays
  - Purge report files older than cleanupDays
  - Trim agent-metrics.json run history to last 100 entries per agent

No LLM. No vault content changes.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

TASK_ID         = "cleanup-agent"
SCRIPT_BASENAME = "cleanup_agent.py"
CLEANUP_DAYS    = 90
MAX_METRIC_RUNS = 100

_ORCH_STATE   = _AGENTS_DIR / "runtime" / "state"
_MASTER_LOG   = _ORCH_STATE / "logs" / "automation.log"
_AGENT_STATE  = _AGENTS_DIR / "cleanup" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_REPORTS_DIR  = _AGENT_STATE / "reports"
_METRICS_FILE = _AGENTS_DIR / "shared" / "state" / "agent-metrics.json"


class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"cleanup-agent_{today}.log"
        self._master = _MASTER_LOG

    def _write(self, level: str, msg: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{TASK_ID}] {level}: {msg}"
        print(line, flush=True)
        self._master.parent.mkdir(parents=True, exist_ok=True)
        for p in (self._master, self._daily):
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, m: str)    -> None: self._write("INFO",  m)
    def warning(self, m: str) -> None: self._write("WARN",  m)
    def error(self, m: str)   -> None: self._write("ERROR", m)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, count: int = 0, failed: int = 0) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write("INFO", f"--- DONE --- processed={count} failed={failed} elapsed={elapsed}s")


def _purge_old_files(directory: Path, keep_days: int, log: _Logger) -> int:
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
                log.info(f"Purged: {f.name} (age={( datetime.now(timezone.utc) - mtime).days}d)")
                deleted += 1
        except Exception as exc:
            log.warning(f"Could not delete {f.name}: {exc}")
    return deleted


def purge_logs(keep_days: int, log: _Logger) -> int:
    """Purge all agent log directories older than keep_days."""
    total = 0
    for logs_dir in _AGENTS_DIR.glob("*/state/logs"):
        total += _purge_old_files(logs_dir, keep_days, log)
    return total


def purge_reports(keep_days: int, log: _Logger) -> int:
    """Purge all agent report directories older than keep_days."""
    total = 0
    for reports_dir in _AGENTS_DIR.glob("*/state/reports"):
        total += _purge_old_files(reports_dir, keep_days, log)
    return total


def trim_metrics(max_runs: int, log: _Logger) -> int:
    """Trim agent-metrics.json to max_runs entries per agent. Returns total runs removed."""
    if not _METRICS_FILE.exists():
        return 0
    try:
        data: dict = json.loads(_METRICS_FILE.read_text(encoding="utf-8"))
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


def main() -> None:
    log = _Logger()
    t0  = log.start()
    count = 0

    count += purge_logs(CLEANUP_DAYS, log)
    count += purge_reports(CLEANUP_DAYS, log)
    count += trim_metrics(MAX_METRIC_RUNS, log)

    log.done(t0, count=count)
    sys.exit(0)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "purge_logs",
        "description": f"Delete log files older than {CLEANUP_DAYS} days from all agent log directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keep_days": {"type": "integer", "description": f"Days to retain (default: {CLEANUP_DAYS})", "default": CLEANUP_DAYS},
            },
        },
    },
    {
        "name": "purge_reports",
        "description": f"Delete report files older than {CLEANUP_DAYS} days from all agent report directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keep_days": {"type": "integer", "description": f"Days to retain (default: {CLEANUP_DAYS})", "default": CLEANUP_DAYS},
            },
        },
    },
    {
        "name": "trim_metrics",
        "description": f"Trim agent-metrics.json to the last {MAX_METRIC_RUNS} run entries per agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_runs": {"type": "integer", "description": f"Max runs to keep per agent (default: {MAX_METRIC_RUNS})", "default": MAX_METRIC_RUNS},
            },
        },
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _Logger()
    if name == "purge_logs":
        n = purge_logs(int(args.get("keep_days", CLEANUP_DAYS)), log)
        return f"Purged {n} old log file(s)"
    if name == "purge_reports":
        n = purge_reports(int(args.get("keep_days", CLEANUP_DAYS)), log)
        return f"Purged {n} old report file(s)"
    if name == "trim_metrics":
        n = trim_metrics(int(args.get("max_runs", MAX_METRIC_RUNS)), log)
        return f"Trimmed {n} stale metric run(s)"

    raise ValueError(f"Unknown tool: {name!r}")
