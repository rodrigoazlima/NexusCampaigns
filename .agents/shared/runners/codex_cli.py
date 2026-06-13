"""CodexCliRunner — dispatch via OpenAI Codex CLI (`codex ...`)."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from ..models import RunResult


def _resolve(text: str, context: dict) -> str:
    return re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: str(context.get(m.group(1), m.group(0))),
        text,
    )


class CodexCliRunner:
    """Runs OpenAI Codex CLI as a subprocess in full-auto mode."""

    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        prompt_file:              str | None  = dispatch_config.get("prompt_file")
        prompt_inline:            str        = dispatch_config.get("prompt") or ""
        model:                    str        = dispatch_config.get("model", "o4-mini")
        approval_mode:            str        = dispatch_config.get("approval_mode", "full-auto")
        extra_args:               list[str]  = dispatch_config.get("extra_args", [])
        cwd_mode:                 str        = dispatch_config.get("cwd", "project_root")
        timeout_seconds:          int        = dispatch_config.get("timeout_seconds", 600)
        extra_env:                dict       = dispatch_config.get("env", {})

        cwd = (
            context.get("project_root", ".")
            if cwd_mode == "project_root"
            else context.get("agent_dir", context.get("project_root", "."))
        )

        prompt = prompt_inline
        if prompt_file:
            agent_dir = context.get("agent_dir", ".")
            pf = Path(agent_dir) / prompt_file
            if pf.exists():
                prompt = pf.read_text(encoding="utf-8")

        prompt = _resolve(prompt, context)

        cmd: list[str] = [
            "codex",
            "--model", model,
            "--approval-mode", approval_mode,
            *extra_args,
            prompt,
        ]

        env = {**os.environ, **extra_env}

        t0 = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                timeout=timeout_seconds,
                capture_output=False,
                text=True,
            )
            exit_code = result.returncode
            error     = None
        except subprocess.TimeoutExpired:
            exit_code = 1
            error     = f"codex CLI timed out after {timeout_seconds}s"
        except FileNotFoundError:
            exit_code = 1
            error     = "codex CLI not found — ensure @openai/codex is installed and on PATH"
        except Exception as exc:
            exit_code = 1
            error     = str(exc)

        duration_ms = int((time.monotonic() - t0) * 1000)
        return RunResult(exit_code=exit_code, error=error, duration_ms=duration_ms)
