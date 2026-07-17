"""nexus.runtime.paths — every filesystem path and static constant the
runtime touches. No behavior, so every other module can import from here
without pulling in unrelated logic.
"""

from __future__ import annotations

import re
from pathlib import Path

from nexus.shared.loaders import _find_project_root

PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)
AGENTS_DIR   = PROJECT_ROOT / "agents"

RUNTIME_STATE = AGENTS_DIR / "runtime" / "state"
STATE_JSON    = RUNTIME_STATE / "tasks-state.json"
METRICS_JSON  = RUNTIME_STATE / "agent-metrics.json"
LOCK_FILE     = RUNTIME_STATE / "runner.lock"
LOGS_DIR      = RUNTIME_STATE / "logs"
MASTER_LOG    = LOGS_DIR / "automation.log"
SIGNALS_DIR   = RUNTIME_STATE / "signals"
COSTS_DIR     = RUNTIME_STATE / "costs"
GIT_COMMIT_LOCK_TARGET = RUNTIME_STATE / "git-commit"

LOCK_STALE_SECONDS = 1800   # 30 min
DEFAULT_INTERVAL   = 60     # orchestrator poll cadence

# Signal emitted by the worker loop on any error result; makes the
# maintenance worker due on the next cycle regardless of its interval.
WORKER_ERROR_SIGNAL = "worker-error"

SYSTEM_STATE = PROJECT_ROOT / "system" / "state"
CHAT_QUEUE   = SYSTEM_STATE / "chat-queue.json"
INBOX_QUEUE  = SYSTEM_STATE / "inbox-queue.json"

# Maps dashboard agent name → task_id used in agent.json (LLM agents only)
AGENT_NAME_TO_TASK: dict[str, str] = {
    "lore":           "lore-agent",
    "wiki":           "wiki-agent",
    "classification": "classification-agent",
    "vision":         "vision-agent",
}

MAX_METRICS_RUNS = 100

# Parses itemsProcessed / itemsFailed from agent DONE lines.
# Handles both runner format (processed=N) and shared.Logger format (classified: N).
# Spec keywords: classified|enriched|repairs|processed|converted|generated|linked
DONE_PARSE_RE = re.compile(
    r"(?:classified|enriched|repairs|processed|converted|generated|linked)"
    r"[=:\s]+(\d+)"
    r".*?"
    r"(?:failed|failures)[=:\s]+(\d+)",
    re.IGNORECASE,
)

# Maps dispatch.type → attribute name on AgentDispatchConfig
DISPATCH_TYPE_FIELD: dict[str, str] = {
    "cli":            "cli",
    "openai-api":     "openai_api",
    "claude-api":     "claude_api",
    "gemini-api":     "gemini_api",
    "openrouter-api": "openrouter_api",
    "claude-code":    "claude_code",
    "lm-studio":      "lm_studio",
    "codex-cli":      "codex_cli",
}
