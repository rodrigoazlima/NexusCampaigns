"""OpenAICompatRunner — OpenAI API (and compatible endpoints: LM Studio, Ollama)."""

from __future__ import annotations

from ..models import RunResult


class OpenAICompatRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        raise NotImplementedError("OpenAICompatRunner not yet implemented")
