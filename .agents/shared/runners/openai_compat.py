"""OpenAICompatRunner — OpenAI REST API and any compatible endpoint.

Supported: OpenAI, LM Studio (localhost:1234), LocalRouter (localhost:8080),
Ollama, and any server that speaks the OpenAI chat completions schema.

Dispatch config keys (from OpenAIApiConfig):
  base_url         str   — API base URL, e.g. http://localhost:1234/v1
  model            str   — model identifier
  system_file      str?  — path to system prompt, relative to agent_dir
  prompt_file      str?  — path to user prompt, relative to agent_dir
  max_tokens       int   — default 1024
  temperature      float — default 0.0
  timeout_seconds  int   — default 120

Auth: OPENAI_API_KEY env var. For local endpoints set to any non-empty string.

Retry policy (per llm-integration.spec.md):
  - 3 attempts, 3 s backoff between retries
  - URLError (server offline) → skip batch silently (exit_code=1, no permanent failure)
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

_MAX_RETRIES   = 3
_RETRY_DELAY_S = 3.0


class OpenAICompatRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        cfg             = dispatch_config
        base_url        = cfg["base_url"].rstrip("/")
        model           = cfg["model"]
        max_tokens      = int(cfg.get("max_tokens", 1024))
        temperature     = float(cfg.get("temperature", 0.0))
        timeout_s       = int(cfg.get("timeout_seconds", 120))
        api_key         = os.environ.get("OPENAI_API_KEY", "lm-studio")
        agent_dir       = Path(context["agent_dir"])

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
        url     = f"{base_url}/chat/completions"
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
        }

        t0         = time.monotonic()
        last_error: str | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    raw    = json.loads(resp.read().decode("utf-8"))
                    text   = raw["choices"][0]["message"]["content"]
                    return RunResult(
                        exit_code=0,
                        output=text,
                        duration_ms=_ms(t0),
                    )

            except urllib.error.URLError as exc:
                # Server offline — skip batch silently, no retry
                return RunResult(
                    exit_code=1,
                    error=f"LLM server unreachable ({base_url}): {exc}",
                    duration_ms=_ms(t0),
                )

            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    return RunResult(
                        exit_code=1,
                        error=f"API auth error HTTP {exc.code}: {exc.reason}",
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
