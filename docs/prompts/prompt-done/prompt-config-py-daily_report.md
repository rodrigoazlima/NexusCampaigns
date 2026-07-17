You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.system/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.system/config/<script_name>.json`)
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
   - Do not include code - only configuration.

---

**Script to analyze:**

# review\tools\daily_report.py
"""review.tools.daily_report

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

from shared import (  # noqa: E402
    FrontmatterIO,
    Logger,
    describe_violations,
    extract_wikilinks,
    is_orphan,
    slugs_from_relationships,
)

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
_QUEUE_FILE   = _PROJECT_ROOT / ".system" / "state" / "inbox-queue.json"

_LOG_LINE_RE  = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([^\]]+)\] (\w+): (.+)$"
)
_WIKILINK_RE  = re.compile(r"\[\[[^\]]+\]\]")


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


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
        elif "--- DONE" in message:
            s["completedRuns"] += 1

        if level == "ERROR":
            s["errors"] += 1
        elif level == "WARN":
            s["warnings"] += 1

    return summaries


# ---------------------------------------------------------------------------
# Queue depth
# ---------------------------------------------------------------------------

def _load_queue_depth() -> tuple[int, int, int]:
    """Return (total, pending, done) from inbox-queue.json.

    pending = any agent slot is 'pending'
    done    = all non-skip agent slots are 'done'
    """
    if not _QUEUE_FILE.exists():
        return 0, 0, 0

    try:
        raw = json.loads(_QUEUE_FILE.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception:
        return 0, 0, 0

    total = len(raw)
    pending_count = 0
    done_count = 0

    for entry in raw.values():
        agents = entry.get("agents", {}) if isinstance(entry, dict) else {}
        slots = [v for v in agents.values() if v != "skip"]
        if any(v == "pending" for v in slots):
            pending_count += 1
        elif slots and all(v == "done" for v in slots):
            done_count += 1

    return total, pending_count, done_count


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


def _vault_health(fio: FrontmatterIO, log: Logger) -> dict[str, Any]:
    pending_review: list[str] = []
    orphans:        list[str] = []
    quality_scores: dict[str, int] = {}

    if _PROCESSING.is_dir():
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

    library_violations = _library_link_violations(fio)
    queue_depth, queue_pending, queue_done = _load_queue_depth()

    return {
        "pendingReview":         pending_review,
        "orphans":               orphans,
        "qualityScores":         quality_scores,
        "queueDepth":            queue_depth,
        "queuePending":          queue_pending,
        "queueDone":             queue_done,
        "libraryLinkViolations": library_violations,
    }


# ---------------------------------------------------------------------------
# Library link-rule violation detection (linking-rules.spec.md)
# ---------------------------------------------------------------------------

def _library_link_violations(fio: FrontmatterIO) -> list[dict[str, Any]]:
    """Scan 02-Library/ for entities missing required outbound link types."""
    violations: list[dict[str, Any]] = []
    if not _LIBRARY.is_dir():
        return violations

    for md_path in sorted(_LIBRARY.glob("**/*.md")):
        try:
            fm, body = fio.read(md_path)
        except Exception:
            continue

        entity_type = fm.get("type", "")
        rel = md_path.relative_to(_PROJECT_ROOT).as_posix()

        linked = (
            slugs_from_relationships(fm.get("relationships") or [])
            + extract_wikilinks(body)
        )

        if is_orphan(linked):
            violations.append({
                "path":       rel,
                "type":       entity_type,
                "violations": ["no outbound links (orphan)"],
            })
        else:
            issues = describe_violations(entity_type, linked)
            if issues:
                violations.append({
                    "path":       rel,
                    "type":       entity_type,
                    "violations": issues,
                })

    return violations


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


def _write_reports_js(log: Logger) -> None:
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
    log = _make_logger()
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

    n_pending    = len(health["pendingReview"])
    n_orphans    = len(health["orphans"])
    n_violations = len(health["libraryLinkViolations"])
    log.info(
        f"Vault health: pendingReview={n_pending} orphans={n_orphans}"
        f" libraryLinkViolations={n_violations}"
        f" queueDepth={health['queueDepth']} queuePending={health['queuePending']}"
        f" queueDone={health['queueDone']}"
    )

    log.done(t0, key="processed", count=1, failed=0)
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
        "description": (
            "Scan 01-Processing/ for pending reviews, orphans, and quality scores. "
            "Also scans 02-Library/ for link-rule violations (missing required links per linking-rules.spec.md). "
            "Loads inbox-queue.json for queue depth metrics (total/pending/done). "
            "Returns health dict including libraryLinkViolations and queueDepth."
        ),
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

    log = _make_logger()
    fio = FrontmatterIO()

    if name == "parse_automation_log":
        hours = int(args.get("hours", 24))
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        summaries = _parse_automation_log(since)
        return _json.dumps(summaries, indent=2, default=str)

    if name == "scan_vault_health":
        health = _vault_health(fio, log)
        return _json.dumps(health, indent=2, default=str)

    if name == "write_report":
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
├── .system/config/
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

