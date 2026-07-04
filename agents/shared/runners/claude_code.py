"""ClaudeCodeRunner — dispatch via Claude Code CLI (`claude -p ...`)."""

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


class ClaudeCodeRunner:
    """Runs Claude Code CLI as a subprocess in non-interactive (-p) mode."""

    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        prompt_file               = dispatch_config.get("prompt_file")
        prompt_inline             = dispatch_config.get("prompt") or ""
        extra_args: list[str]     = dispatch_config.get("extra_args", ["--dangerously-skip-permissions"])
        cwd_mode: str             = dispatch_config.get("cwd", "project_root")
        timeout_seconds: int      = dispatch_config.get("timeout_seconds", 600)
        extra_env: dict[str, str] = dispatch_config.get("env", {})

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

        cmd: list[str] = ["claude", "-p", prompt, *extra_args]

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
            error     = f"claude CLI timed out after {timeout_seconds}s"
        except FileNotFoundError:
            exit_code = 1
            error     = "claude CLI not found — ensure Claude Code is installed and on PATH"
        except Exception as exc:
            exit_code = 1
            error     = str(exc)

        duration_ms = int((time.monotonic() - t0) * 1000)
        return RunResult(exit_code=exit_code, error=error, duration_ms=duration_ms)
