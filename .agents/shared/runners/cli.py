"""CliRunner — subprocess dispatch for cli agents."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from ..models import RunResult


class CliRunner:
    """Runs a command as a subprocess. stdout/stderr stream to the console."""

    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        command         = dispatch_config["command"]
        args            = dispatch_config.get("args", [])
        cwd_mode        = dispatch_config.get("cwd", "project_root")
        timeout_seconds = dispatch_config.get("timeout_seconds", 300)
        extra_env       = dispatch_config.get("env", {})

        # Substitute sys.executable so venv Python is always used
        if command in ("python", "python3"):
            command = sys.executable

        cwd = (
            context.get("project_root", ".")
            if cwd_mode == "project_root"
            else context.get("agent_dir", context.get("project_root", "."))
        )

        env = {**os.environ, **extra_env}
        cmd = [command, *args]

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
            error     = f"Process timed out after {timeout_seconds}s"
        except FileNotFoundError as exc:
            exit_code = 1
            error     = f"Command not found: {command!r} — {exc}"
        except Exception as exc:
            exit_code = 1
            error     = str(exc)

        duration_ms = int((time.monotonic() - t0) * 1000)
        return RunResult(exit_code=exit_code, error=error, duration_ms=duration_ms)
