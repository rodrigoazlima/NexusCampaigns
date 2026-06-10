"""OpenRouterRunner — OpenRouter unified gateway."""

from __future__ import annotations

from ..models import RunResult


class OpenRouterRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        raise NotImplementedError("OpenRouterRunner not yet implemented")
