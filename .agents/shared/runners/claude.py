"""ClaudeRunner — Anthropic Claude API dispatch runner.

Two dispatch patterns (per agent-dispatch.spec.md):

  Tool-use pattern (primary — all active agents)
    Requires: tools_module
    Behaviour: agentic loop calling tools until end_turn or max_tool_rounds.

  Prompt pattern (simple generation)
    Requires: prompt_file (no tools_module)
    Behaviour: single non-agentic API call, returns text response.

Dispatch config keys (from ClaudeApiConfig):
  model            str   — Claude model ID
  system_file      str?  — path to system prompt, relative to agent_dir
  tools_module     str?  — dotted import path for agent's tool module
  prompt_file      str?  — user prompt .md, relative to agent_dir; prompt pattern only
  history_file     str?  — filename for persistent chat history, under agent state/
  max_tokens       int   — default 4096
  temperature      float — default 0
  timeout_seconds  int   — default 120 (per API call)
  max_tool_rounds  int   — agentic loop cap, default 20

Tools module must expose:
  TOOLS: list[dict]                        — Anthropic tool definitions
  call_tool(name, args, context) -> str    — tool dispatcher

Retry policy (spec: agent-dispatch.spec.md):
  - API 5xx: retry up to 3× with 3s backoff
  - API 401/403: no retry, exit_code=1
  - Timeout: no retry, exit_code=1
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

from ..models import RunResult
from . import _resolve_placeholders

_MAX_RETRIES   = 3
_RETRY_DELAY_S = 3.0


class ClaudeRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        try:
            import anthropic
        except ImportError:
            return RunResult(
                exit_code=1,
                error="anthropic package not installed — run: pip install anthropic",
            )

        cfg          = dispatch_config
        agent_dir    = Path(context["agent_dir"])
        agents_dir   = Path(context.get("agents_dir", str(agent_dir.parent)))
        model_id     = cfg["model"]
        timeout_s    = float(cfg.get("timeout_seconds", 120))
        temperature  = float(cfg.get("temperature", 0.0))

        client = anthropic.Anthropic(timeout=timeout_s)

        # ------------------------------------------------------------------ #
        # System prompt
        # ------------------------------------------------------------------ #
        system = ""
        if cfg.get("system_file"):
            p = agent_dir / cfg["system_file"]
            if p.exists():
                system = _resolve_placeholders(
                    p.read_text(encoding="utf-8").strip(), context
                )

        # ------------------------------------------------------------------ #
        # Route to appropriate pattern
        # ------------------------------------------------------------------ #
        if cfg.get("tools_module"):
            return self._run_tool_use(
                cfg, context, client, agent_dir, agents_dir,
                model_id, system, temperature,
            )
        else:
            return self._run_prompt(
                cfg, context, client, agent_dir,
                model_id, system, temperature,
            )

    # ---------------------------------------------------------------------- #
    # Prompt pattern — single non-agentic call
    # ---------------------------------------------------------------------- #

    def _run_prompt(
        self,
        cfg: dict,
        context: dict,
        client: Any,
        agent_dir: Path,
        model_id: str,
        system: str,
        temperature: float,
    ) -> RunResult:
        try:
            import anthropic
        except ImportError:
            return RunResult(exit_code=1, error="anthropic package not installed")

        prompt = _load_file(agent_dir, cfg.get("prompt_file"), context)

        create_kwargs: dict[str, Any] = {
            "model":       model_id,
            "messages":    [{"role": "user", "content": prompt}],
            "max_tokens":  int(cfg.get("max_tokens", 4096)),
            "temperature": temperature,
        }
        if system:
            create_kwargs["system"] = system

        t0 = time.monotonic()
        last_error: Optional[str] = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp = client.messages.create(**create_kwargs)

                input_tokens  = getattr(getattr(resp, "usage", None), "input_tokens",  0)
                output_tokens = getattr(getattr(resp, "usage", None), "output_tokens", 0)

                text = "".join(
                    blk.text for blk in resp.content if hasattr(blk, "text")
                )
                return RunResult(
                    exit_code=0,
                    output=text,
                    duration_ms=_ms(t0),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=model_id,
                )

            except anthropic.AuthenticationError as exc:
                return RunResult(
                    exit_code=1,
                    error=f"Claude API auth error: {exc}",
                    duration_ms=_ms(t0),
                    model=model_id,
                )
            except anthropic.PermissionDeniedError as exc:
                return RunResult(
                    exit_code=1,
                    error=f"Claude API permission denied: {exc}",
                    duration_ms=_ms(t0),
                    model=model_id,
                )
            except anthropic.APITimeoutError as exc:
                return RunResult(
                    exit_code=1,
                    error=f"Claude API timeout: {exc}",
                    duration_ms=_ms(t0),
                    model=model_id,
                )
            except anthropic.InternalServerError as exc:
                last_error = f"Claude API 5xx error (attempt {attempt + 1}): {exc}"
            except Exception as exc:
                last_error = f"Claude API error (attempt {attempt + 1}): {exc}"

            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_S)

        return RunResult(
            exit_code=1,
            error=last_error,
            duration_ms=_ms(t0),
            model=model_id,
        )

    # ---------------------------------------------------------------------- #
    # Tool-use pattern — agentic loop
    # ---------------------------------------------------------------------- #

    def _run_tool_use(
        self,
        cfg: dict,
        context: dict,
        client: Any,
        agent_dir: Path,
        agents_dir: Path,
        model_id: str,
        system: str,
        temperature: float,
    ) -> RunResult:
        try:
            import anthropic
        except ImportError:
            return RunResult(exit_code=1, error="anthropic package not installed")

        project_root = Path(context["project_root"])

        # ------------------------------------------------------------------ #
        # Load tools module
        # ------------------------------------------------------------------ #
        module_path = cfg["tools_module"]
        if str(agents_dir) not in sys.path:
            sys.path.insert(0, str(agents_dir))
        try:
            mod = importlib.import_module(module_path)
        except (ModuleNotFoundError, ImportError):
            # Fallback: file-path import handles stdlib name conflicts (e.g. 'token')
            parts = module_path.split(".")
            file_path = agents_dir / Path(*parts).with_suffix(".py")
            if not file_path.exists():
                return RunResult(
                    exit_code=1,
                    error=f"Failed to import tools_module {module_path!r}: "
                          f"module not found and file {file_path} does not exist",
                )
            try:
                spec = importlib.util.spec_from_file_location(module_path, file_path)
                mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
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
        tools: list[dict] = list(getattr(mod, "TOOLS", []))

        # ------------------------------------------------------------------ #
        # Chat history (persistent across runs for multi-turn continuity)
        # ------------------------------------------------------------------ #
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

        messages.append({
            "role": "user",
            "content": (
                f"Execute your scheduled task now. "
                f"Project root: {project_root}. "
                f"Agent dir: {agent_dir}. "
                f"Use your tools to complete the task, then stop."
            ),
        })

        # ------------------------------------------------------------------ #
        # Agentic loop
        # ------------------------------------------------------------------ #
        max_rounds      = int(cfg.get("max_tool_rounds", 20))
        max_tokens_run  = cfg.get("max_tokens_per_run")
        exit_code       = 0
        last_error: Optional[str] = None
        total_input     = 0
        total_output    = 0

        t0 = time.monotonic()

        try:
            for round_num in range(max_rounds):
                create_kwargs: dict[str, Any] = {
                    "model":       model_id,
                    "messages":    messages,
                    "max_tokens":  int(cfg.get("max_tokens", 4096)),
                    "temperature": temperature,
                }
                if system:
                    create_kwargs["system"] = system
                if tools:
                    create_kwargs["tools"] = tools

                resp = _create_with_retry(client, create_kwargs)
                if resp is None:
                    exit_code  = 1
                    last_error = "Claude API 5xx — max retries exhausted mid-loop"
                    break

                if hasattr(resp, "usage") and resp.usage:
                    total_input  += getattr(resp.usage, "input_tokens",  0)
                    total_output += getattr(resp.usage, "output_tokens", 0)

                assistant_content = _serialise_content(resp.content)
                messages.append({"role": "assistant", "content": assistant_content})

                if resp.stop_reason == "end_turn":
                    break

                if resp.stop_reason != "tool_use":
                    break

                if max_tokens_run and (total_input + total_output) > max_tokens_run:
                    last_error = (
                        f"Token budget exceeded "
                        f"({total_input + total_output} > {max_tokens_run}). Stopping."
                    )
                    break

                tool_results: list[dict] = []
                for blk in resp.content:
                    if blk.type != "tool_use":
                        continue
                    try:
                        result = mod.call_tool(blk.name, blk.input, context)
                    except Exception as exc:
                        result     = f"ERROR: {exc}"
                        exit_code  = 1
                        last_error = str(exc)

                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": blk.id,
                        "content":     str(result),
                    })

                messages.append({"role": "user", "content": tool_results})

            else:
                exit_code  = 1
                last_error = f"Agent hit max_tool_rounds={max_rounds} without completing"

        except Exception as exc:
            exit_code  = 1
            last_error = str(exc)

        finally:
            if history_path is not None:
                _save_history(history_path, messages)

        return RunResult(
            exit_code=exit_code,
            error=last_error,
            duration_ms=_ms(t0),
            input_tokens=total_input,
            output_tokens=total_output,
            model=model_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_with_retry(client: Any, kwargs: dict) -> Any:
    """Call client.messages.create() with 3× retry on 5xx. Returns None on exhaustion."""
    try:
        import anthropic
    except ImportError:
        return None

    for attempt in range(_MAX_RETRIES):
        try:
            return client.messages.create(**kwargs)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                anthropic.APITimeoutError):
            raise  # propagate non-retryable errors immediately
        except anthropic.InternalServerError:
            pass  # 5xx — retry
        except Exception:
            raise

        if attempt < _MAX_RETRIES - 1:
            time.sleep(_RETRY_DELAY_S)

    return None


def _load_file(agent_dir: Path, filename: str | None, context: dict) -> str:
    if not filename:
        return ""
    p = agent_dir / filename
    if not p.exists():
        return ""
    return _resolve_placeholders(p.read_text(encoding="utf-8").strip(), context)


def _serialise_content(content: Any) -> list[dict]:
    """Convert SDK content blocks to plain dicts for JSON serialisation."""
    result = []
    for blk in content:
        if hasattr(blk, "model_dump"):
            result.append(blk.model_dump())
        elif hasattr(blk, "__dict__"):
            result.append({k: v for k, v in blk.__dict__.items() if not k.startswith("_")})
        else:
            result.append({"type": "unknown", "text": str(blk)})
    return result


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
