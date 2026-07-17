"""nexus.runtime.dispatch_config — resolves a task_id to an AgentDispatchConfig
(agent.json, falling back to registry.yaml's default_dispatch), plus the
small pieces of agent-folder convention that resolution depends on: the
task_id → agent-directory name mapping, commit_scope parsing from AGENT.md,
and unwrapping the type-specific dispatch sub-config.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from nexus.shared import (
    AgentDispatchConfig,
    AgentFolderConfig,
    DispatchError,
    Logger,
    TaskDispatchEntry,
)
from nexus.shared.loaders import load_registry
from nexus.shared.models import LmStudioConfig

from .paths import AGENTS_DIR, DISPATCH_TYPE_FIELD, PROJECT_ROOT

_COMMIT_SCOPE_RE = re.compile(r"^commit_scope:\s*\n((?:[ \t]+-[^\n]+\n?)+)", re.MULTILINE)
_SCOPE_ITEM_RE   = re.compile(r"^\s+-\s+(.+)$", re.MULTILINE)


def agent_name_from_task_id(task_id: str) -> str:
    """Map task_id → agent directory name.

    Examples:
      vision-agent → vision
      lore-agent   → lore
    """
    name = re.sub(r"-agent(?:-.*)?$", "", task_id)
    return name or task_id


def load_agent_dispatch(task_id: str, log: Logger) -> Optional[AgentDispatchConfig]:
    """Load and return the AgentDispatchConfig for task_id from agent.json.

    Falls back to registry.yaml's `default_dispatch` (paired with the
    agent's registered `tools:` entry) when agent.json is missing or has no
    entry for this task_id — lets an agent run off its registry.yaml
    declaration alone. See docs/specs/agents/agent-dispatch-settings.md.
    """
    agent_name = agent_name_from_task_id(task_id)
    agent_json = AGENTS_DIR / agent_name / "agent.json"

    if agent_json.exists():
        try:
            raw = json.loads(agent_json.read_text(encoding="utf-8"))
            folder_cfg = AgentFolderConfig.model_validate(raw)
        except Exception as exc:
            log.error(f"Failed to parse {agent_json}: {exc} — skipping {task_id}")
            return None

        entry: Optional[TaskDispatchEntry] = folder_cfg.tasks.get(task_id)
        if entry is not None:
            return entry.dispatch
        log.warning(f"Task ID {task_id!r} not found in {agent_json} — trying registry default_dispatch")
    else:
        log.warning(f"agent.json not found: {agent_json} — trying registry default_dispatch")

    return build_default_dispatch(agent_name, task_id, log)


def build_default_dispatch(agent_name: str, task_id: str, log: Logger) -> Optional[AgentDispatchConfig]:
    """Build a fallback AgentDispatchConfig from registry.yaml's default_dispatch
    + the agent's `tools:` entry. Returns None if either is unavailable."""
    try:
        registry = load_registry(PROJECT_ROOT)
    except Exception as exc:
        log.error(f"Could not load registry.yaml for default_dispatch fallback: {exc} — skipping {task_id}")
        return None

    default_cfg = registry.default_dispatch
    reg_agent   = registry.agents.get(agent_name)
    if default_cfg is None or reg_agent is None or not reg_agent.tools:
        log.error(
            f"No agent.json and no usable registry default for {task_id!r} "
            f"(agent={agent_name!r}) — skipping"
        )
        return None

    tool_path    = reg_agent.tools[0]                       # e.g. "tools/ingestion_agent.py"
    tool_stem    = Path(tool_path).stem                     # "ingestion_agent"
    tools_module = f"{agent_name}.tools.{tool_stem}"

    log.warning(
        f"Using registry default_dispatch for {task_id!r}: "
        f"type={default_cfg.type} model={default_cfg.model} tools_module={tools_module}"
    )

    if default_cfg.type != "lm-studio":
        log.error(f"default_dispatch type {default_cfg.type!r} not supported by fallback builder — skipping {task_id}")
        return None

    return AgentDispatchConfig(
        type=default_cfg.type,
        lm_studio=LmStudioConfig(
            base_url=default_cfg.base_url,
            model=default_cfg.model,
            timeout_seconds=default_cfg.timeout_seconds,
            system_file=default_cfg.system_file,
            tools_module=tools_module,
        ),
    )


def read_agent_commit_scope(task_id: str) -> list[str]:
    """Parse commit_scope from the agent's AGENT.md. Returns [] if absent."""
    agent_name = agent_name_from_task_id(task_id)
    agent_md = AGENTS_DIR / agent_name / "AGENT.md"
    if not agent_md.exists():
        return []
    try:
        content = agent_md.read_text(encoding="utf-8")
        m = _COMMIT_SCOPE_RE.search(content)
        if not m:
            return []
        return [item.strip() for item in _SCOPE_ITEM_RE.findall(m.group(1)) if item.strip()]
    except Exception:
        return []


def extract_dispatch_sub(dispatch: AgentDispatchConfig) -> dict:
    """Return the type-specific sub-config as a plain dict."""
    field = DISPATCH_TYPE_FIELD.get(dispatch.type)
    if field is None:
        raise DispatchError(f"Unknown dispatch type: {dispatch.type!r}")
    sub = getattr(dispatch, field, None)
    if sub is None:
        raise DispatchError(
            f"Dispatch type is {dispatch.type!r} but the '{field}' block is absent in agent.json"
        )
    return sub.model_dump()
