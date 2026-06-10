"""GeminiRunner — Google Gemini API."""

from __future__ import annotations

from ..models import RunResult


class GeminiRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        raise NotImplementedError("GeminiRunner not yet implemented")
