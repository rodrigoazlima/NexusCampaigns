"""nexus.shared.container_runtime

Podman/Docker runtime detection, the Windows/WSL host-gateway workarounds,
and the localhost-rewrite helper - shared by nexus.tasks.sandbox_run and
nexus.shared.runners.docker so there's one source of truth for this
hard-won, Windows-specific plumbing instead of two copies that drift.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .loaders import _find_project_root

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)
_SYSTEM_STATE = _PROJECT_ROOT / "system" / "state"

# Written by setup-service.ps1 (Find-Podman/Find-Docker) - a service process
# doesn't inherit whatever PATH found podman/docker at install time, so it's
# persisted here as a fallback instead of trusting PATH alone.
RUNTIME_STATE_PATH = _SYSTEM_STATE / "container-runtime.json"


class ContainerRuntimeError(RuntimeError):
    """No usable container runtime, or its daemon/machine isn't reachable."""


def _runtime_fallback_path(name: str, state_path: Path) -> Optional[str]:
    """Look up name's exe path from container-runtime.json, if setup-service.ps1
    recorded one and it still exists on disk."""
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, json.JSONDecodeError):
        return None
    path = data.get(name)
    return path if path and Path(path).is_file() else None


def detect_runtime(preferred: Optional[str] = None, state_path: Optional[Path] = None) -> str:
    state_path = state_path or RUNTIME_STATE_PATH
    candidates = [preferred] if preferred else ["podman", "docker"]
    for name in candidates:
        if not name:
            continue
        if shutil.which(name):
            return name
        fallback = _runtime_fallback_path(name, state_path)
        if fallback:
            # Not on this process's PATH - widen it with the fallback's own
            # dir so every `subprocess.run([name, ...])` call below still
            # resolves `name` by bare command.
            os.environ["PATH"] = os.pathsep.join(
                [str(Path(fallback).parent), os.environ.get("PATH", "")]
            )
            return name
    raise ContainerRuntimeError(
        "No container runtime found on PATH or in system/state/container-runtime.json "
        "(checked: podman, docker). Install Podman or Docker, or re-run setup-service.ps1 "
        "to refresh the fallback path."
    )


def runtime_version(binary: str) -> str:
    result = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    return (result.stdout or result.stderr or "").strip()


def preflight(binary: str) -> None:
    result = subprocess.run(
        [binary, "info"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if result.returncode != 0:
        raise ContainerRuntimeError(
            f"`{binary} info` failed (exit {result.returncode}): {result.stderr.strip()}\n"
            f"Hint: is the {binary} machine/daemon running? (this tool will not auto-start it)"
        )


def host_gateway_name(runtime_bin: str) -> str:
    return "host.docker.internal" if runtime_bin == "docker" else "host.containers.internal"


def podman_wsl_gateway_ip() -> Optional[str]:
    """Podman Desktop's WSL machine is a second hop: `--add-host ...:host-gateway`
    resolves to the WSL VM's own loopback, not Windows, so a container can
    open TCP to the VM but never reaches a Windows-side server (e.g. LM
    Studio) - refused, not timed out, since something local answers on that
    address. The VM's own default route already points at the real Windows
    host, so ask it directly and use that concrete IP instead of the magic
    keyword."""
    result = subprocess.run(
        ["podman", "machine", "ssh", "--", "ip", "route", "show", "default"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        return None
    match = re.search(r"default via (\S+)", result.stdout)
    return match.group(1) if match else None


def rewrite_localhost(text: str, host_gateway: str) -> str:
    return text.replace("localhost", host_gateway).replace("127.0.0.1", host_gateway)
