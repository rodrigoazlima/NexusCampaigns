"""nexus.runtime.state - tasks-state.json I/O (per-task/worker lastRun)."""

from __future__ import annotations

import json

from nexus.shared import TASKS_STATE_DEFAULT, TasksState, TaskStateEntry

from .paths import STATE_JSON


def load_state() -> TasksState:
    if not STATE_JSON.exists():
        STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        STATE_JSON.write_text(
            json.dumps(TASKS_STATE_DEFAULT, indent=2),
            encoding="utf-8",
        )
    raw: dict = json.loads(STATE_JSON.read_text(encoding="utf-8"))
    return {k: TaskStateEntry.model_validate(v) for k, v in raw.items()}


def save_state(state: TasksState) -> None:
    tmp = STATE_JSON.with_suffix(".tmp")
    payload = {k: {"lastRun": v.lastRun.isoformat()} for k, v in state.items()}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(STATE_JSON)
