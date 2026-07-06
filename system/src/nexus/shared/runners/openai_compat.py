"""OpenAICompatRunner — OpenAI REST API and any compatible endpoint.

Supported: OpenAI, LM Studio (localhost:1234), LocalRouter (localhost:8080),
Ollama, and any server that speaks the OpenAI chat completions schema.

Two dispatch patterns (mirrors shared.runners.claude):

  Tool-use pattern — set tools_module
    Agentic loop: model emits tool_calls, we execute mod.call_tool(), feed
    results back, repeat until finish_reason == "stop" or max_tool_rounds.
    Anthropic-style TOOLS (name/description/input_schema) are converted to
    OpenAI's function-calling schema on the fly.

  Prompt pattern — no tools_module
    Single non-agentic chat completion, returns text response.

Dispatch config keys (from OpenAIApiConfig / LmStudioConfig):
  base_url         str   — API base URL, e.g. http://localhost:1234/v1
  model            str   — model identifier
  system_file      str?  — path to system prompt, relative to agent_dir
  prompt_file      str?  — path to user prompt, relative to agent_dir (prompt pattern only)
  tools_module     str?  — dotted import path for agent's tool module (tool-use pattern only)
  history_file     str?  — filename for persistent chat history, under agent state/
  max_tool_rounds  int   — agentic loop cap, default 20
  max_tokens       int   — default 1024
  temperature      float — default 0.0
  timeout_seconds  int   — default 120

Auth: OPENAI_API_KEY env var. For local endpoints set to any non-empty string.

Retry policy (per llm-integration.spec.md):
  - 3 attempts, 3 s backoff between retries
  - URLError (server offline) → skip batch silently (exit_code=1, no permanent failure)
  - HTTP 4xx → exit_code=1, no retry
  - HTTP 5xx / 429 → retry up to 3×
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from ..models import RunResult
from . import _resolve_placeholders

_MAX_RETRIES   = 3
_RETRY_DELAY_S = 3.0


class OpenAICompatRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        cfg       = dispatch_config
        agent_dir = Path(context["agent_dir"])

        if cfg.get("tools_module"):
            agents_dir = Path(context.get("agents_dir", str(agent_dir.parent)))
            return self._run_tool_use(cfg, context, agent_dir, agents_dir)
        return self._run_prompt(cfg, agent_dir)

    # ---------------------------------------------------------------------- #
    # Prompt pattern — single non-agentic call
    # ---------------------------------------------------------------------- #

    def _run_prompt(self, cfg: dict, agent_dir: Path) -> RunResult:
        system = _load_file(agent_dir, cfg.get("system_file"), {})
        prompt = _load_file(agent_dir, cfg.get("prompt_file"), {})

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        t0 = time.monotonic()
        resp, error = _post_chat(cfg, messages)
        if resp is None:
            return RunResult(exit_code=1, error=error, duration_ms=_ms(t0))

        try:
            text = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            return RunResult(
                exit_code=1,
                error=f"Unexpected response structure: {exc}",
                duration_ms=_ms(t0),
            )

        return RunResult(exit_code=0, output=text, duration_ms=_ms(t0))

    # ---------------------------------------------------------------------- #
    # Tool-use pattern — agentic loop
    # ---------------------------------------------------------------------- #

    def _run_tool_use(
        self, cfg: dict, context: dict, agent_dir: Path, agents_dir: Path,
    ) -> RunResult:
        project_root = Path(context["project_root"])

        module_path = cfg["tools_module"]
        if str(agents_dir) not in sys.path:
            sys.path.insert(0, str(agents_dir))
        try:
            mod = importlib.import_module(module_path)
        except (ModuleNotFoundError, ImportError):
            parts     = module_path.split(".")
            file_path = agents_dir / Path(*parts).with_suffix(".py")
            if not file_path.exists():
                return RunResult(
                    exit_code=1,
                    error=f"Failed to import tools_module {module_path!r}: "
                          f"module not found and file {file_path} does not exist",
                )
            try:
                spec = importlib.util.spec_from_file_location(module_path, file_path)
                mod  = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                sys.modules[module_path] = mod
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception as exc:
                return RunResult(
                    exit_code=1,
                    error=f"Failed to load tools_module {module_path!r} from {file_path}: {exc}",
                )
        except Exception as exc:
            return RunResult(
                exit_code=1,
                error=f"Failed to import tools_module {module_path!r}: {exc}",
            )

        tools = _to_openai_tools(list(getattr(mod, "TOOLS", [])))

        history_path: Optional[Path] = None
        messages: list[dict] = []
        if cfg.get("history_file"):
            history_path = agent_dir / "state" / cfg["history_file"]
            history_path.parent.mkdir(parents=True, exist_ok=True)
            if history_path.exists():
                try:
                    messages = json.loads(history_path.read_text(encoding="utf-8"))
                except Exception:
                    messages = []

        system = _load_file(agent_dir, cfg.get("system_file"), context)
        if system and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system})

        messages.append({
            "role": "user",
            "content": (
                f"Execute your scheduled task now. "
                f"Project root: {project_root}. "
                f"Agent dir: {agent_dir}. "
                f"Use your tools to complete the task, then stop."
            ),
        })

        max_rounds   = int(cfg.get("max_tool_rounds", 20))
        exit_code    = 0
        last_error: Optional[str] = None

        t0 = time.monotonic()

        try:
            for _round in range(max_rounds):
                resp, error = _post_chat(cfg, messages, tools=tools)
                if resp is None:
                    exit_code  = 1
                    last_error = error or "LLM request failed — max retries exhausted mid-loop"
                    break

                try:
                    message = resp["choices"][0]["message"]
                except (KeyError, IndexError) as exc:
                    exit_code  = 1
                    last_error = f"Unexpected response structure: {exc}"
                    break

                messages.append(message)
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    break

                for tc in tool_calls:
                    fn   = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = mod.call_tool(name, args, context)
                    except Exception as exc:
                        result     = f"ERROR: {exc}"
                        exit_code  = 1
                        last_error = str(exc)

                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content":      str(result),
                    })
            else:
                exit_code  = 1
                last_error = f"Agent hit max_tool_rounds={max_rounds} without completing"

        finally:
            if history_path is not None:
                _save_history(history_path, messages)

        return RunResult(exit_code=exit_code, error=last_error, duration_ms=_ms(t0))


# ---------------------------------------------------------------------------
# HTTP + retry
# ---------------------------------------------------------------------------

def _post_chat(
    cfg: dict, messages: list[dict], tools: Optional[list[dict]] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """POST one chat-completions call with 3x retry on 5xx/429. Returns (response, error)."""
    base_url    = cfg["base_url"].rstrip("/")
    model       = cfg["model"]
    max_tokens  = int(cfg.get("max_tokens", 1024))
    temperature = float(cfg.get("temperature", 0.0))
    timeout_s   = int(cfg.get("timeout_seconds", 120))
    api_key     = os.environ.get("OPENAI_API_KEY", "lm-studio")

    url     = f"{base_url}/chat/completions"
    payload: dict[str, Any] = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    if tools:
        payload["tools"]      = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error: Optional[str] = None
    for attempt in range(_MAX_RETRIES):
        body = json.dumps(payload).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8")), None

        except urllib.error.URLError as exc:
            return None, f"LLM server unreachable ({base_url}): {exc}"

        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return None, f"API auth error HTTP {exc.code}: {exc.reason}"
            if exc.code not in (429, 500, 502, 503, 504):
                return None, f"HTTP {exc.code}: {exc.reason}"
            retry_after = exc.headers.get("retry-after") if exc.headers else None
            last_error = f"HTTP {exc.code}: {exc.reason} (attempt {attempt + 1})"
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_retry_delay(retry_after))
            continue

        except json.JSONDecodeError as exc:
            last_error = f"Non-JSON response (attempt {attempt + 1}): {exc}"

        except Exception as exc:
            last_error = f"Request error (attempt {attempt + 1}): {exc}"

        if attempt < _MAX_RETRIES - 1:
            time.sleep(_RETRY_DELAY_S)

    return None, last_error


def _retry_delay(retry_after: Optional[str], default: float = _RETRY_DELAY_S) -> float:
    if retry_after:
        try:
            return max(float(retry_after), default)
        except ValueError:
            pass
    return default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_openai_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic-style tool defs (name/description/input_schema) to
    OpenAI's function-calling schema (type/function/parameters)."""
    return [
        {
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t.get("description", ""),
                "parameters":  t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in anthropic_tools
    ]


def _load_file(agent_dir: Path, filename: str | None, context: dict) -> str:
    if not filename:
        return ""
    p = agent_dir / filename
    if not p.exists():
        return ""
    return _resolve_placeholders(p.read_text(encoding="utf-8").strip(), context)


def _save_history(path: Path, messages: list[dict]) -> None:
    trimmed = messages[-50:]
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(trimmed, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)
