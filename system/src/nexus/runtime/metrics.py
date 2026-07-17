"""nexus.runtime.metrics — per-run metrics for agents and workers
(state/agent-metrics.json). No cost/token data — see nexus.runtime.costs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from .paths import DONE_PARSE_RE, MASTER_LOG, MAX_METRICS_RUNS, METRICS_JSON


def load_metrics() -> dict:
    if not METRICS_JSON.exists():
        return {}
    try:
        # Strip BOM: Windows PS may write UTF-8-BOM to agent-metrics.json
        text = METRICS_JSON.read_text(encoding="utf-8").lstrip("﻿")
        return json.loads(text)
    except Exception:
        return {}


def save_metrics(data: dict) -> None:
    tmp = METRICS_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(METRICS_JSON)


def parse_agent_items(task_id: str, after: datetime) -> tuple[int, int]:
    """Return (processed, failed) from the agent's first DONE line after 'after'."""
    if not MASTER_LOG.exists():
        return 0, 0
    try:
        tag = f"[{task_id}]"
        # Log timestamps are local time (datetime.now()), so convert UTC 'after' to local
        ts_after = after.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        for line in MASTER_LOG.read_text(encoding="utf-8").splitlines():
            if tag not in line or "--- DONE" not in line:
                continue
            ts_m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
            if ts_m and ts_m.group(1) >= ts_after:
                m = DONE_PARSE_RE.search(line)
                if m:
                    return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 0, 0


def record_metrics(
    task_id: str,
    started_at: datetime,
    finished_at: datetime,
    items_processed: int,
    items_failed: int,
) -> None:
    data = load_metrics()
    entry = data.setdefault(task_id, {"runs": []})
    entry["runs"].append({
        "startedAt":      started_at.isoformat(),
        "finishedAt":     finished_at.isoformat(),
        "durationMs":     int((finished_at - started_at).total_seconds() * 1000),
        "itemsProcessed": items_processed,
        "itemsFailed":    items_failed,
    })
    if len(entry["runs"]) > MAX_METRICS_RUNS:
        entry["runs"] = entry["runs"][-MAX_METRICS_RUNS:]
    save_metrics(data)


def record_worker_metrics(
    name: str,
    started_at: datetime,
    processed: int,
    failed: int,
    duration_ms: int,
) -> None:
    """Worker run entry (worker-contract.spec.md §Metrics). No cost entry ever."""
    data = load_metrics()
    entry = data.setdefault(name, {"runs": []})
    entry["kind"] = "worker"
    entry["runs"].append({
        "at":         started_at.isoformat(),
        "processed":  processed,
        "failed":     failed,
        "durationMs": duration_ms,
    })
    if len(entry["runs"]) > MAX_METRICS_RUNS:
        entry["runs"] = entry["runs"][-MAX_METRICS_RUNS:]
    save_metrics(data)
