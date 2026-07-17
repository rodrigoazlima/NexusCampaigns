"""nexus.runtime.costs - per-run token/cost tracking (state/costs/*.json).
Agent runs only; workers never record a cost entry (worker-contract.spec.md)."""

from __future__ import annotations

import json
from datetime import datetime

from .paths import COSTS_DIR


def record_cost(
    task_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    started_at: datetime,
) -> None:
    """Append per-run token usage to the daily cost file (atomic write)."""
    if not model and not input_tokens and not output_tokens:
        return  # non-Claude runner - nothing to record

    today = started_at.strftime("%Y-%m-%d")
    COSTS_DIR.mkdir(parents=True, exist_ok=True)
    cost_file = COSTS_DIR / f"costs-{today}.json"

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
