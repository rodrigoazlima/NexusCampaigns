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

# cleanup\tools\cleanup_agent.py
"""cleanup.tools.cleanup_agent

Cleanup Agent — log/report rotation and metrics trimming.
  - Purge log files older than cleanupDays (read from agent.json, default 90)
  - Purge report files older than cleanupDays
  - Trim agent-metrics.json run history to last 100 entries per agent
  - Write CleanupReport to state/reports/cleanup-{YYYY-MM-DD}.json

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

from shared.logger import Logger  # noqa: E402

TASK_ID         = "cleanup-agent"
SCRIPT_BASENAME = "cleanup_agent.py"
MAX_METRIC_RUNS = 100

_AGENT_DIR    = _AGENTS_DIR / "cleanup"
_AGENT_STATE  = _AGENT_DIR / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_REPORTS_DIR  = _AGENT_STATE / "reports"
_MASTER_LOG   = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_METRICS_FILE = _AGENTS_DIR / "runtime" / "state" / "agent-metrics.json"
_AGENT_JSON   = _AGENT_DIR / "agent.json"


def _load_cleanup_days() -> int:
    """Read cleanupDays from agent.json top-level field. Default 90."""
    try:
        cfg = json.loads(_AGENT_JSON.read_text(encoding="utf-8"))
        return int(cfg.get("cleanupDays", 90))
    except Exception:
        return 90


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
    """Purge log files older than keep_days across all agent log directories."""
    total = 0
    for logs_dir in _AGENTS_DIR.glob("*/state/logs"):
        total += _purge_dir(logs_dir, keep_days, log)
    return total


def purge_reports(keep_days: int, log: Logger) -> int:
    """Purge report files older than keep_days across all agent report directories."""
    total = 0
    for reports_dir in _AGENTS_DIR.glob("*/state/reports"):
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
    cleanup_days = _load_cleanup_days()
    log = _make_logger()
    t0  = log.start()

    logs_deleted    = purge_logs(cleanup_days, log)
    reports_deleted = purge_reports(cleanup_days, log)
    metrics_trimmed = trim_metrics(MAX_METRIC_RUNS, log)

    _write_report(logs_deleted, reports_deleted, metrics_trimmed)

    total = logs_deleted + reports_deleted + metrics_trimmed
    log.done(t0, key="processed", count=total, failed=0)
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
        "description": "Delete log files older than cleanupDays from all agent log directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keep_days": {
                    "type": "integer",
                    "description": "Days to retain (default: read from agent.json)",
                    "default": 90,
                },
            },
        },
    },
    {
        "name": "purge_reports",
        "description": "Delete report files older than cleanupDays from all agent report directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keep_days": {
                    "type": "integer",
                    "description": "Days to retain (default: read from agent.json)",
                    "default": 90,
                },
            },
        },
    },
    {
        "name": "trim_metrics",
        "description": f"Trim agent-metrics.json to the last {MAX_METRIC_RUNS} run entries per agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_runs": {
                    "type": "integer",
                    "description": f"Max runs to keep per agent (default: {MAX_METRIC_RUNS})",
                    "default": MAX_METRIC_RUNS,
                },
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

    cleanup_days = _load_cleanup_days()
    log = _make_logger()

    if name == "purge_logs":
        n = purge_logs(int(args.get("keep_days", cleanup_days)), log)
        return f"Purged {n} old log file(s)"
    if name == "purge_reports":
        n = purge_reports(int(args.get("keep_days", cleanup_days)), log)
        return f"Purged {n} old report file(s)"
    if name == "trim_metrics":
        n = trim_metrics(int(args.get("max_runs", MAX_METRIC_RUNS)), log)
        return f"Trimmed {n} stale metric run(s)"

    raise ValueError(f"Unknown tool: {name!r}")


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

