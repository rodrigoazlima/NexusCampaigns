"""ClaudeRunner retries on 429 rate-limit errors instead of failing immediately."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import httpx

from nexus.shared.runners.claude import _create_with_retry, _retry_after


def _rate_limit_error(retry_after: str | None = None) -> anthropic.RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, headers=headers, request=request)
    return anthropic.RateLimitError("rate limited", response=response, body=None)


def test_retry_after_reads_header():
    exc = _rate_limit_error(retry_after="7")
    assert _retry_after(exc, default=3.0) == 7.0


def test_retry_after_falls_back_to_default_without_header():
    exc = _rate_limit_error()
    assert _retry_after(exc, default=3.0) == 3.0


def test_create_with_retry_recovers_from_one_rate_limit(monkeypatch):
    monkeypatch.setattr("nexus.shared.runners.claude.time.sleep", lambda _s: None)

    client = MagicMock()
    ok_response = MagicMock(stop_reason="end_turn")
    client.messages.create.side_effect = [_rate_limit_error(retry_after="1"), ok_response]

    result = _create_with_retry(client, {"model": "claude-x"})

    assert result is ok_response
    assert client.messages.create.call_count == 2
