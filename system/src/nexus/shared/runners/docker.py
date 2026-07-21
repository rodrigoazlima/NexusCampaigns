"""DockerRunner - dispatch via a container built from the agent's own
Dockerfile (nc-vision-agent and future externally-hosted agents).

Unlike nexus.tasks.sandbox_run (which copies in-tree agent code + vault scope
into a per-run image, then diffs/applies the result), this runner bind-mounts
the shared nexus library, the vault, and the agent's own state dir straight
through. The container writes directly to the real host files - no
extraction/diff/apply/VaultGuard-in-runner step needed, since the mounted
.system/src/nexus/shared/vault_guard.py already enforces the same guarantees
from inside the container, same as it does for every other agent.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from ..container_runtime import (
    ContainerRuntimeError,
    detect_runtime,
    host_gateway_name,
    podman_wsl_gateway_ip,
    preflight,
    rewrite_localhost,
)
from ..models import RunResult


class DockerRunner:
    """Builds the agent's own Dockerfile and runs it with the shared library,
    vault, and agent state bind-mounted in."""

    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        image           = dispatch_config["image"]
        dockerfile      = dispatch_config.get("dockerfile", "dockerfile")
        timeout_seconds = dispatch_config.get("timeout_seconds", 1800)
        extra_env       = dispatch_config.get("env", {})

        project_root = Path(context.get("project_root", "."))
        agent_dir    = Path(context.get("agent_dir", "."))

        t0 = time.monotonic()
        try:
            runtime_bin = detect_runtime()
            preflight(runtime_bin)
        except ContainerRuntimeError as exc:
            return RunResult(exit_code=1, error=str(exc), duration_ms=int((time.monotonic() - t0) * 1000))

        build = subprocess.run(
            [runtime_bin, "build", "-t", image, "-f", str(agent_dir / dockerfile), str(agent_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if build.returncode != 0:
            return RunResult(
                exit_code=1,
                output=build.stdout,
                error=f"image build failed for {image}: {build.stderr.strip()}",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        gateway = host_gateway_name(runtime_bin)
        registry_src = project_root / "agents" / "registry.yaml"

        with tempfile.TemporaryDirectory(prefix="nexus-docker-run-") as tmp:
            registry_mount = Path(tmp) / "registry.yaml"
            registry_mount.write_text(
                rewrite_localhost(registry_src.read_text(encoding="utf-8"), gateway)
                if registry_src.exists() else "",
                encoding="utf-8",
            )

            state_dir = agent_dir / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            cmd = [
                runtime_bin, "run", "--rm",
                "-v", f"{project_root / 'system'}:/app/.system",
                "-v", f"{project_root / '.knowledge-base'}:/app/.knowledge-base",
                "-v", f"{state_dir}:/app/state",
                "-v", f"{registry_mount}:/app/registry.yaml:ro",
            ]
            if runtime_bin == "podman":
                gateway_ip = podman_wsl_gateway_ip()
                cmd += [f"--add-host={gateway}:{gateway_ip or 'host-gateway'}"]
            for key, val in extra_env.items():
                cmd += ["-e", f"{key}={val}"]
            cmd.append(image)

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=timeout_seconds,
                )
                exit_code = result.returncode
                output    = (result.stdout or "") + (result.stderr or "")
                error     = None
            except subprocess.TimeoutExpired:
                exit_code = 1
                output    = ""
                error     = f"Container timed out after {timeout_seconds}s"

        duration_ms = int((time.monotonic() - t0) * 1000)
        return RunResult(exit_code=exit_code, output=output, error=error, duration_ms=duration_ms)
