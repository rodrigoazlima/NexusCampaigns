"""nexus.runtime.registry_yaml - reads registry.yaml as a raw dict (execution
order, pipeline mode, workers block, agent.json synthesis defaults).

Distinct from nexus.shared.loaders.load_registry, which parses the same file
into a validated RegistryConfig for dispatch fallback - this one stays a
permissive dict read since callers here only need a few loosely-typed blocks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from nexus.shared import Logger

from .paths import AGENTS_DIR


def load_registry_dict() -> dict:
    """Load and return the full parsed registry.yaml. Returns {} on any error."""
    registry = AGENTS_DIR / "registry.yaml"
    if not registry.exists():
        return {}
    try:
        from ruamel.yaml import YAML  # available via requirements.txt
        return YAML().load(registry.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_execution_order() -> list[str]:
    """Load execution_order list from registry.yaml. Returns [] on any error."""
    return list(load_registry_dict().get("execution_order", []))


def load_pipeline_mode() -> str:
    """Load pipeline_mode ('sync' or 'async') from registry.yaml. Defaults to 'sync'."""
    mode = load_registry_dict().get("pipeline_mode", "sync")
    return mode if mode == "async" else "sync"


def synthesize_agent_json(agent_name: str, entry: dict) -> Optional[dict]:
    """Build a default agent.json payload for `agent_name` from its registry.yaml entry.

    Most active agents in this codebase are self-contained CLI scripts (each
    reads its own LLM endpoint/config internally), so the synthesized dispatch
    is `cli: python <tool>` by default. An agent whose code lives elsewhere
    (e.g. vision, dispatched via its own externally-cloned Docker image - see
    shared/runners/docker.py) declares its own `dispatch:` block directly in
    registry.yaml, which is used as-is instead of the generic per-tool cli
    synthesis. Returns None if the entry has no task_id and no tools/dispatch
    override (e.g. the static runtime, or a "planned" agent).
    """
    task_id = entry.get("task_id")
    dispatch_override = entry.get("dispatch")
    tools = entry.get("tools") or []
    if not task_id or not (tools or dispatch_override):
        return None

    interval    = int(entry.get("interval_seconds", 3600))
    description = entry.get("description") or f"{agent_name} agent"
    is_llm_bound = str(entry.get("llm", "none")) != "none"

    if dispatch_override:
        return {"tasks": {task_id: {
            "intervalSeconds": interval,
            "description": description,
            "dispatch": dict(dispatch_override),
        }}}

    tasks: dict = {}
    for i, tool in enumerate(tools):
        stem = Path(tool).stem
        tid = task_id if i == 0 else f"{task_id}-{stem}"
        tasks[tid] = {
            "intervalSeconds": interval,
            "description": description if i == 0 else f"{description} ({stem})",
            "dispatch": {
                "type": "cli",
                "cli": {
                    "command": "python",
                    "args": [f"agents/{agent_name}/{tool}"],
                    "cwd": "project_root",
                    "timeout_seconds": 1800 if is_llm_bound else 300,
                },
            },
        }
    return {"tasks": tasks}


def ensure_agent_jsons(log: Logger) -> None:
    """Self-heal: create agent.json for any active agent missing one.

    agent.json is gitignored (matches the blanket `*.json` rule) so a fresh
    clone/install starts with zero of them, and the scheduler discovers zero
    tasks. Regenerate the missing ones from registry.yaml defaults so the
    pipeline works out of the box; a hand-edited agent.json is never touched.
    """
    for agent_name, entry in (load_registry_dict().get("agents") or {}).items():
        if entry.get("status") != "active":
            continue
        agent_json = AGENTS_DIR / agent_name / "agent.json"
        if agent_json.exists():
            continue
        payload = synthesize_agent_json(agent_name, entry)
        if payload is None:
            continue
        agent_json.parent.mkdir(parents=True, exist_ok=True)
        agent_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.warning(f"agent.json missing for '{agent_name}' - synthesized from registry.yaml defaults: {agent_json}")
