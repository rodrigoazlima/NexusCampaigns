"""shared.runners - dispatch runner factory.

get_runner(dispatch_type) → IRunner
_resolve_placeholders(text, context) → str
"""

from __future__ import annotations

import re

from ..interfaces import DispatchError, IRunner

__all__ = ["IRunner", "get_runner", "_resolve_placeholders"]


def _resolve_placeholders(text: str, context: dict) -> str:
    """Replace {{key}} with context[key]. Unknown keys are left unchanged."""
    return re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: str(context.get(m.group(1), m.group(0))),
        text,
    )

_TYPE_TO_MODULE: dict[str, str] = {
    "cli":            ".cli",
    "openai-api":     ".openai_compat",
    "claude-api":     ".claude",
    "gemini-api":     ".gemini",
    "openrouter-api": ".openrouter",
    "claude-code":    ".claude_code",
    "lm-studio":      ".openai_compat",   # OpenAI-compatible endpoint
    "codex-cli":      ".codex_cli",
    "docker":         ".docker",
}

_TYPE_TO_CLASS: dict[str, str] = {
    "cli":            "CliRunner",
    "openai-api":     "OpenAICompatRunner",
    "claude-api":     "ClaudeRunner",
    "gemini-api":     "GeminiRunner",
    "openrouter-api": "OpenRouterRunner",
    "claude-code":    "ClaudeCodeRunner",
    "lm-studio":      "OpenAICompatRunner",
    "codex-cli":      "CodexCliRunner",
    "docker":         "DockerRunner",
}


def get_runner(dispatch_type: str) -> IRunner:
    """Return the appropriate runner for dispatch_type.

    Raises DispatchError for unknown types.
    Runners are imported lazily so missing optional deps only fail at dispatch time.
    """
    module_path = _TYPE_TO_MODULE.get(dispatch_type)
    class_name  = _TYPE_TO_CLASS.get(dispatch_type)
    if module_path is None:
        raise DispatchError(f"Unknown dispatch type: {dispatch_type!r}")

    import importlib
    mod = importlib.import_module(module_path, package=__name__)
    return getattr(mod, class_name)()
