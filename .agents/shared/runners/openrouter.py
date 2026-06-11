"""OpenRouterRunner — OpenRouter unified gateway.

OpenRouter exposes an OpenAI-compatible API at https://openrouter.ai/api/v1.
Any model available on OpenRouter can be used (e.g. anthropic/claude-sonnet-4-6,
google/gemini-2.5-flash, meta-llama/llama-3.1-8b-instruct).

Dispatch config keys (from OpenRouterApiConfig):
  model            str   — OpenRouter model slug, e.g. anthropic/claude-sonnet-4-6
  system_file      str?  — path to system prompt, relative to agent_dir
  prompt_file      str?  — path to user prompt, relative to agent_dir
  max_tokens       int   — default 4096
  temperature      float — default 0.0
  timeout_seconds  int   — default 180

Auth: OPENROUTER_API_KEY env var.

Retry policy (per llm-integration.spec.md):
  - 3 attempts, 3 s backoff between retries
  - URLError (connection failure) → exit_code=1, no retry
  - HTTP 4xx → exit_code=1, no retry
  - HTTP 5xx → retry up to 3×
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..models import RunResult
from . import _resolve_placeholders

_BASE_URL      = "https://openrouter.ai/api/v1/chat/completions"
_MAX_RETRIES   = 3
_RETRY_DELAY_S = 3.0

# OpenRouter identifies the requesting application via these optional headers.
_SITE_URL  = "https://github.com/nexuscampaigns"
_SITE_NAME = "NexusCampaigns"


class OpenRouterRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        cfg         = dispatch_config
        model       = cfg["model"]
        max_tokens  = int(cfg.get("max_tokens", 4096))
        temperature = float(cfg.get("temperature", 0.0))
        timeout_s   = int(cfg.get("timeout_seconds", 180))
        api_key     = os.environ.get("OPENROUTER_API_KEY", "")
        agent_dir   = Path(context["agent_dir"])

        if not api_key:
            return RunResult(exit_code=1, error="OPENROUTER_API_KEY env var not set")

        # ------------------------------------------------------------------ #
        # Load prompts
        # ------------------------------------------------------------------ #
        system = _load_file(agent_dir, cfg.get("system_file"), context)
        prompt = _load_file(agent_dir, cfg.get("prompt_file"), context)

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # ------------------------------------------------------------------ #
        # API call with retries
        # ------------------------------------------------------------------ #
        payload = {
            "model":       model,
            "messages":    messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }
        body    = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  _SITE_URL,
            "X-Title":       _SITE_NAME,
        }

        t0         = time.monotonic()
        last_error: str | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(_BASE_URL, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    raw  = json.loads(resp.read().decode("utf-8"))
                    text = raw["choices"][0]["message"]["content"]
                    return RunResult(
                        exit_code=0,
                        output=text,
                        duration_ms=_ms(t0),
                    )

            except urllib.error.URLError as exc:
                return RunResult(
                    exit_code=1,
                    error=f"OpenRouter unreachable: {exc}",
                    duration_ms=_ms(t0),
                )

            except urllib.error.HTTPError as exc:
                if exc.code in (401, 402, 403):
                    return RunResult(
                        exit_code=1,
                        error=f"OpenRouter auth/billing error HTTP {exc.code}: {exc.reason}",
                        duration_ms=_ms(t0),
                    )
                # 5xx — retry
                last_error = f"HTTP {exc.code}: {exc.reason} (attempt {attempt + 1})"

            except (KeyError, IndexError) as exc:
                last_error = f"Unexpected response structure (attempt {attempt + 1}): {exc}"

            except json.JSONDecodeError as exc:
                last_error = f"Non-JSON response (attempt {attempt + 1}): {exc}"

            except Exception as exc:
                last_error = f"Request error (attempt {attempt + 1}): {exc}"

            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_S)

        return RunResult(exit_code=1, error=last_error, duration_ms=_ms(t0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_file(agent_dir: Path, filename: str | None, context: dict) -> str:
    if not filename:
        return ""
    p = agent_dir / filename
    if not p.exists():
        return ""
    return _resolve_placeholders(p.read_text(encoding="utf-8").strip(), context)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
