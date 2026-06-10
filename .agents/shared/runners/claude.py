"""ClaudeRunner — Anthropic Claude API."""

from __future__ import annotations

from ..models import RunResult


class ClaudeRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        raise NotImplementedError("ClaudeRunner not yet implemented")
