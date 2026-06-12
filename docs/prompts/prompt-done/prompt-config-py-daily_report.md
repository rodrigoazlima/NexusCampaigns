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

# review\tools\daily_report.py
"""review.tools.08_daily_report

Aggregates automation logs + vault health into a JSON report every 15 min.
Rebuilds state/reports/reports-data.js after each report.
No LLM. No 02-Library writes. May inject suggestedQuality into 01-Processing files.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import FrontmatterIO  # noqa: E402

TASK_ID         = "review-agent"
SCRIPT_BASENAME = "daily_report.py"

_VAULT_ROOT   = _PROJECT_ROOT / "knowledge-base"
_PROCESSING   = _VAULT_ROOT / "01-Processing"
_LIBRARY      = _VAULT_ROOT / "02-Library"
_ORCH_STATE   = _AGENTS_DIR / "runtime" / "state"
_MASTER_LOG   = _ORCH_STATE / "logs" / "automation.log"
_AGENT_STATE  = _AGENTS_DIR / "review" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_REPORTS_DIR  = _AGENT_STATE / "reports"

_LOG_LINE_RE  = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([^\]]+)\] (\w+): (.+)$"
)
_WIKILINK_RE  = re.compile(r"\[\[[^\]]+\]\]")


class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"daily-report_{today}.log"
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


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def _parse_automation_log(since: datetime) -> dict[str, Any]:
    summaries: dict[str, Any] = {}

    if not _MASTER_LOG.exists():
        return summaries

    for line in _MASTER_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _LOG_LINE_RE.match(line)
        if not m:
            continue

        ts_str, task_id, level, message = m.groups()
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if ts < since:
            continue

        if task_id not in summaries:
            summaries[task_id] = {
                "runs": 0, "completedRuns": 0, "errors": 0,
                "warnings": 0, "firstRun": ts_str, "lastRun": ts_str,
            }

        s = summaries[task_id]
        s["lastRun"] = ts_str

        if "--- START ---" in message:
            s["runs"] += 1
        elif "--- DONE ---" in message:
            s["completedRuns"] += 1

        if level == "ERROR":
            s["errors"] += 1
        elif level == "WARN":
            s["warnings"] += 1

    return summaries


# ---------------------------------------------------------------------------
# Vault health
# ---------------------------------------------------------------------------

def _quality_score(fm: dict, body: str) -> int:
    score = 0
    if any(h in body for h in ["## Description", "## Details"]):
        score += 2
    if fm.get("relationships") and any("[[" in r for r in fm.get("relationships", [])):
        score += 2
    if len(fm.get("tags", [])) >= 3:
        score += 2
    if fm.get("type"):
        score += 2
    if fm.get("source"):
        score += 2
    return min(score, 10)


def _vault_health(fio: FrontmatterIO, log: _Logger) -> dict[str, Any]:
    pending_review: list[str] = []
    orphans:        list[str] = []
    quality_scores: dict[str, int] = {}

    if not _PROCESSING.is_dir():
        return {
            "pendingReview": pending_review,
            "orphans": orphans,
            "qualityScores": quality_scores,
        }

    for md_path in sorted(_PROCESSING.glob("**/*.md")):
        try:
            fm, body = fio.read(md_path)
        except Exception:
            continue

        rel = md_path.relative_to(_PROJECT_ROOT).as_posix()

        if not fm.get("reviewed") or fm.get("status") == "draft":
            pending_review.append(rel)

        if not _WIKILINK_RE.search(body):
            orphans.append(rel)

        score = _quality_score(fm, body)
        quality_scores[rel] = score

        if fm.get("quality", 0) == 0 and "suggestedQuality" not in fm:
            try:
                fm["suggestedQuality"] = score
                fio.write(md_path, fm, body)
            except Exception as exc:
                log.warning(f"Could not inject suggestedQuality in {md_path.name}: {exc}")

    return {
        "pendingReview": pending_review,
        "orphans": orphans,
        "qualityScores": quality_scores,
    }


# ---------------------------------------------------------------------------
# Report + JS data file
# ---------------------------------------------------------------------------

def _load_tasks_config() -> dict[str, Any]:
    """Discover task configs by scanning */agent.json files."""
    tasks = []
    agents_dir = Path(__file__).resolve().parents[2]
    for agent_json in sorted(agents_dir.glob("*/agent.json")):
        try:
            raw = json.loads(agent_json.read_text(encoding="utf-8"))
            for tid, entry in raw.get("tasks", {}).items():
                tasks.append({
                    "id":              tid,
                    "intervalSeconds": entry.get("intervalSeconds"),
                    "description":     entry.get("description", ""),
                })
        except Exception:
            continue
    return {"tasks": tasks}


def _write_reports_js(log: _Logger) -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    for f in sorted(_REPORTS_DIR.glob("report-*.json")):
        try:
            reports.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue

    tasks_cfg = _load_tasks_config()
    js_content = (
        f"const REPORTS_DATA = {json.dumps(reports, indent=2)};\n"
        f"const TASK_CONFIG = {json.dumps(tasks_cfg, indent=2)};\n"
    )

    js_path = _REPORTS_DIR / "reports-data.js"
    js_path.write_text(js_content, encoding="utf-8")
    log.info(f"Rebuilt reports-data.js ({len(reports)} report(s))")


def main() -> None:
    log = _Logger()
    t0  = log.start()
    fio = FrontmatterIO()

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    now   = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    today = now.strftime("%Y-%m-%d")

    log.info("Parsing automation.log for last 24h")
    agent_summaries = _parse_automation_log(since)

    log.info("Scanning vault health")
    health = _vault_health(fio, log)

    report: dict[str, Any] = {
        "generatedAt":    now.isoformat(),
        "date":           today,
        "agentSummaries": agent_summaries,
        "vaultHealth":    health,
    }

    report_path = _REPORTS_DIR / f"report-{today}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    log.info(f"Report written: {report_path.name}")

    _write_reports_js(log)

    n_pending = len(health["pendingReview"])
    n_orphans = len(health["orphans"])
    log.info(f"Vault health: pendingReview={n_pending} orphans={n_orphans}")

    log.done(t0, count=1)
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
        "name": "parse_automation_log",
        "description": "Parse automation.log for the last N hours and return per-agent summaries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "How many hours back to scan (default: 24)", "default": 24},
            },
        },
    },
    {
        "name": "scan_vault_health",
        "description": "Scan 01-Processing/ for pending reviews, orphans, and quality scores. Returns health dict.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "write_report",
        "description": "Write the daily JSON report file and rebuild reports-data.js for the dashboard.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import json as _json
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _Logger()
    fio = FrontmatterIO()

    if name == "parse_automation_log":
        from datetime import timedelta
        hours = int(args.get("hours", 24))
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        summaries = _parse_automation_log(since)
        return _json.dumps(summaries, indent=2, default=str)

    if name == "scan_vault_health":
        health = _vault_health(fio, log)
        return _json.dumps(health, indent=2, default=str)

    if name == "write_report":
        from datetime import timedelta
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)
        today = now.strftime("%Y-%m-%d")
        summaries = _parse_automation_log(since)
        health = _vault_health(fio, log)
        report = {
            "generatedAt":    now.isoformat(),
            "date":           today,
            "agentSummaries": summaries,
            "vaultHealth":    health,
        }
        report_path = _REPORTS_DIR / f"report-{today}.json"
        report_path.write_text(_json.dumps(report, indent=2, default=str), encoding="utf-8")
        _write_reports_js(log)
        return f"Report written: {report_path.name}"

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

