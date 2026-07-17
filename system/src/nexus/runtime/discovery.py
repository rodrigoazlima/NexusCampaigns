"""nexus.runtime.discovery - scans agents/*/agent.json into the ordered task
list the scheduler dispatches from."""

from __future__ import annotations

import json

from nexus.shared import AgentFolderConfig, TaskDispatchEntry

from .dispatch_config import agent_name_from_task_id
from .log import make_logger
from .paths import AGENTS_DIR
from .registry_yaml import ensure_agent_jsons, load_execution_order


def discover_tasks() -> list[tuple[str, TaskDispatchEntry]]:
    """Scan agents/*/agent.json and return all (task_id, TaskDispatchEntry) pairs.

    Tasks are ordered by execution_order from registry.yaml. Agents absent from
    execution_order are appended after all ordered agents, sorted alphabetically.
    """
    ensure_agent_jsons(make_logger())
    result: list[tuple[str, TaskDispatchEntry]] = []
    for agent_json in AGENTS_DIR.glob("*/agent.json"):
        try:
            raw = json.loads(agent_json.read_text(encoding="utf-8"))
            folder = AgentFolderConfig.model_validate(raw)
            for task_id, entry in folder.tasks.items():
                result.append((task_id, entry))
        except Exception as exc:
            make_logger().warning(f"Skipping {agent_json}: {exc}")

    order = load_execution_order()
    if order:
        def _sort_key(item: tuple[str, TaskDispatchEntry]) -> tuple[int, str]:
            agent_name = agent_name_from_task_id(item[0])
            try:
                return (order.index(agent_name), item[0])
            except ValueError:
                return (len(order), item[0])  # unlisted agents last
        result.sort(key=_sort_key)
    else:
        result.sort(key=lambda t: t[0])  # stable fallback: alphabetical by task_id

    return result
