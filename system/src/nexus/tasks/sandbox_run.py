"""nexus.tasks.sandbox_run

Runs one LLM agent inside an isolated Podman/Docker container instead of
directly against the live vault + repo state. Builds an image containing
only that agent's own folder plus the vault/state files its AGENT.md
declares (commit_scope, state_files, registry.yaml shared_state), runs
`python -m nexus.runner --task <id> --force` inside it, extracts the
mutated files, diffs them against what went in, and writes back only the
paths inside the agent's declared knowledge-base scope or state files.
Anything else the agent touched is dropped and logged instead of applied.

No LLM calls of its own - pure orchestration + diff/classify. Reuses
read_agent_commit_scope() (nexus.runtime.dispatch_config) rather than
re-parsing AGENT.md, and VaultGuard (nexus.shared.vault_guard) as a
defense-in-depth re-check before every knowledge-base write.

CLI: python -m nexus.tasks.sandbox_run --agent <vision|lore|wiki|classification>
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nexus.runtime.dispatch_config import read_agent_commit_scope
from nexus.runtime.paths import AGENT_NAME_TO_TASK
from nexus.shared import (
    FileLock,
    FrontmatterIO,
    Logger,
    VaultGuard,
    VaultPaths,
    VaultWriteError,
    load_registry,
)
from nexus.shared.loaders import _find_project_root

TASK_ID         = "sandbox"
SCRIPT_BASENAME = "sandbox_run.py"

_PROJECT_ROOT  = _find_project_root(Path(__file__).resolve().parent)
_VAULT_ROOT    = _PROJECT_ROOT / ".knowledge-base"
_AGENTS_DIR    = _PROJECT_ROOT / "agents"
_SYSTEM_STATE  = _PROJECT_ROOT / "system" / "state"
_SANDBOX_STATE = _SYSTEM_STATE / "sandbox"
_RUNS_DIR      = _SANDBOX_STATE / "runs"
_LOGS_DIR      = _SANDBOX_STATE / "logs"
_MASTER_LOG    = _PROJECT_ROOT / "agents" / "runtime" / "state" / "logs" / "automation.log"
_APPLY_LOCK    = _PROJECT_ROOT / "agents" / "runtime" / "state" / "sandbox-apply"

# Written by setup-service.ps1 (Find-Podman/Find-Docker) - the NSSM service
# process doesn't inherit whatever PATH found podman/docker at install time,
# so it's persisted here as a fallback instead of trusting PATH alone.
_RUNTIME_STATE_PATH = _SYSTEM_STATE / "container-runtime.json"

_DIFF_TRUNCATE_LINES = 400
_CONTAINER_LOG_TAIL_LINES = 200
_SKIP_DIRNAMES = {"__pycache__"}
_SKIP_SUFFIXES = {".pyc"}

_BASE_DOCKERFILE = """\
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./pyproject.toml
COPY system/src ./system/src
RUN pip install --no-cache-dir -e .
"""


class SandboxPreflightError(RuntimeError):
    """A precondition failed before (or while) building/running the container -
    no image was run, so nothing needs to be extracted/diffed/recorded."""


def _make_logger() -> Logger:
    return Logger(TASK_ID, SCRIPT_BASENAME, _LOGS_DIR, _MASTER_LOG)


# ---------------------------------------------------------------------------
# Container runtime detection
# ---------------------------------------------------------------------------

def _runtime_fallback_path(name: str) -> Optional[str]:
    """Look up name's exe path from container-runtime.json, if setup-service.ps1
    recorded one and it still exists on disk."""
    if not _RUNTIME_STATE_PATH.exists():
        return None
    try:
        data = json.loads(_RUNTIME_STATE_PATH.read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, json.JSONDecodeError):
        return None
    path = data.get(name)
    return path if path and Path(path).is_file() else None


def _detect_runtime(preferred: Optional[str]) -> str:
    candidates = [preferred] if preferred else ["podman", "docker"]
    for name in candidates:
        if not name:
            continue
        if shutil.which(name):
            return name
        fallback = _runtime_fallback_path(name)
        if fallback:
            # Not on this process's PATH - widen it with the fallback's own
            # dir so every `subprocess.run([name, ...])` call below still
            # resolves `name` by bare command.
            os.environ["PATH"] = os.pathsep.join(
                [str(Path(fallback).parent), os.environ.get("PATH", "")]
            )
            return name
    raise SandboxPreflightError(
        "No container runtime found on PATH or in system/state/container-runtime.json "
        "(checked: podman, docker). Install Podman or Docker, or re-run setup-service.ps1 "
        "to refresh the fallback path."
    )


def _runtime_version(binary: str) -> str:
    result = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    return (result.stdout or result.stderr or "").strip()


def _preflight(binary: str) -> None:
    result = subprocess.run(
        [binary, "info"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if result.returncode != 0:
        raise SandboxPreflightError(
            f"`{binary} info` failed (exit {result.returncode}): {result.stderr.strip()}\n"
            f"Hint: is the {binary} machine/daemon running? (this tool will not auto-start it)"
        )


def _host_gateway_name(runtime_bin: str) -> str:
    return "host.docker.internal" if runtime_bin == "docker" else "host.containers.internal"


def _podman_wsl_gateway_ip() -> Optional[str]:
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


_LOCALHOST_PORT_RE = re.compile(r"(?:localhost|127\.0\.0\.1):(\d+)")


def _registry_localhost_ports(registry_text: str) -> list[int]:
    """Distinct ports registry.yaml points at localhost - these are exactly
    what _rewrite_localhost() will retarget at the container's host gateway,
    so they're what's worth probing before spending ~90s on a build+run that
    will silently no-op if none of them are actually reachable."""
    return sorted({int(p) for p in _LOCALHOST_PORT_RE.findall(registry_text)})


def _probe_wsl_tcp(gateway_ip: str, port: int, timeout: float = 3.0) -> bool:
    """Cheap TCP reachability check run from inside the Podman WSL VM itself
    (not the Windows host) - the same network hop the sandboxed container's
    gvproxy networking takes, so a refused/unreachable result here means the
    container will hit it too, without paying for a full image build+run.

    The probe script is piped over stdin (`python3 -`), not passed as a
    `-c` argument: `podman machine ssh` joins argv with spaces for the
    remote shell without re-quoting, so a `-c` string containing spaces or
    parens gets corrupted into a shell syntax error - which subprocess
    reports as a plain nonzero exit indistinguishable from "port closed",
    a false positive."""
    script = (
        f"import socket,sys\n"
        f"s = socket.socket()\n"
        f"s.settimeout({timeout})\n"
        f"sys.exit(0 if s.connect_ex(('{gateway_ip}', {port})) == 0 else 1)\n"
    )
    result = subprocess.run(
        ["podman", "machine", "ssh", "--", "python3", "-"],
        input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    return result.returncode == 0


def _warn_unreachable_llm_ports(registry_text: str, gateway_ip: Optional[str], log: Logger) -> None:
    """Best-effort: only runs when the WSL gateway IP was resolved. A dead
    port doesn't necessarily mean this agent's run will fail (it may not hit
    that endpoint), so this warns loudly rather than aborting the run."""
    if not gateway_ip:
        return
    for port in _registry_localhost_ports(registry_text):
        if not _probe_wsl_tcp(gateway_ip, port):
            msg = (
                f"local LLM endpoint at localhost:{port} is not reachable from the Podman VM "
                f"(gateway {gateway_ip}) - the sandboxed agent will likely run to completion "
                f"with 0 changes instead of failing. Verify with: podman run --rm "
                f"--add-host=host.containers.internal:{gateway_ip} curlimages/curl "
                f"curl -sf http://host.containers.internal:{port}/v1/models"
            )
            log.warning(msg)
            print(f"warning: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Scope resolution - reuse existing parsers, don't reinvent them
# ---------------------------------------------------------------------------

# AGENT.md's body prose isn't valid standalone YAML (unquoted colons in free
# text), so - like dispatch_config.py's read_agent_commit_scope() - pull just
# the state_files: block out with a narrow regex rather than parsing the
# whole file.
_STATE_FILES_RE = re.compile(r"^state_files:\s*\n((?:[ \t]+-[^\n]+\n?)+)", re.MULTILINE)
_LIST_ITEM_RE   = re.compile(r"^\s+-\s+(.+)$", re.MULTILINE)


def _normalize_state_path(agent: str, entry: str) -> str:
    entry = entry.strip()
    if entry.startswith("state/"):
        return f"agents/{agent}/{entry}"
    return entry


def _read_declared_state_files(agent: str) -> list[str]:
    agent_md = _AGENTS_DIR / agent / "AGENT.md"
    if not agent_md.exists():
        return []
    content = agent_md.read_text(encoding="utf-8")
    m = _STATE_FILES_RE.search(content)
    if not m:
        return []
    items = [item.strip() for item in _LIST_ITEM_RE.findall(m.group(1)) if item.strip()]
    return [_normalize_state_path(agent, i) for i in items if not i.startswith("#")]


def _resolve_scopes(agent: str, task_id: str) -> tuple[list[str], list[str], list[str]]:
    """Returns (commit_scope, state_allowlist, state_readonly) - all repo-relative paths."""
    commit_scope = read_agent_commit_scope(task_id)
    own_state = _read_declared_state_files(agent)

    registry = load_registry(_PROJECT_ROOT)
    entry = registry.agents.get(agent)
    shared_updates = list(entry.shared_state.updates) if entry and entry.shared_state else []
    shared_reads   = list(entry.shared_state.reads) if entry and entry.shared_state else []

    state_allowlist = sorted(set(own_state) | set(shared_updates))
    state_readonly  = sorted(set(shared_reads) - set(state_allowlist))
    return commit_scope, state_allowlist, state_readonly


def _allow_deletes(agent: str, override: Optional[bool]) -> bool:
    if override is not None:
        return override
    registry = load_registry(_PROJECT_ROOT)
    entry = registry.agents.get(agent)
    if entry is None or entry.sandbox is None:
        return False
    return bool(entry.sandbox.allow_deletes)


def _agent_json_dispatch_type(agent: str, task_id: str) -> Optional[str]:
    path = _AGENTS_DIR / agent / "agent.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw.get("tasks", {}).get(task_id, {}).get("dispatch", {}).get("type")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Build context staging
# ---------------------------------------------------------------------------

def _rewrite_localhost(text: str, host_gateway: str) -> str:
    return text.replace("localhost", host_gateway).replace("127.0.0.1", host_gateway)


def _copy_scope_dir(rel: str, staging_dir: Path) -> None:
    """Copy a commit_scope entry (always a vault subdirectory) into staging;
    create it empty if the host hasn't created it yet."""
    src = _PROJECT_ROOT / rel
    dst = staging_dir / rel
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
    elif src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    else:
        dst.mkdir(parents=True, exist_ok=True)


def _copy_state_file(rel: str, staging_dir: Path) -> None:
    """Copy one declared state file into staging; leave it absent if it
    doesn't exist yet on the host - the agent's own state-bootstrap logic
    creates it fresh on first write, same as a live first run. Must NOT
    fabricate a directory in its place (state entries are always files)."""
    src = _PROJECT_ROOT / rel
    if not src.exists():
        return
    dst = staging_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _stage_build_context(
    agent: str,
    commit_scope: list[str],
    state_allowlist: list[str],
    state_readonly: list[str],
    host_gateway: str,
    staging_dir: Path,
) -> None:
    # Always-present roots so `COPY .knowledge-base .knowledge-base` / `COPY
    # system/state system/state` never fail the build even when empty.
    (staging_dir / ".knowledge-base").mkdir(parents=True, exist_ok=True)
    (staging_dir / "system" / "state").mkdir(parents=True, exist_ok=True)

    registry_src = _AGENTS_DIR / "registry.yaml"
    dst_registry = staging_dir / "agents" / "registry.yaml"
    dst_registry.parent.mkdir(parents=True, exist_ok=True)
    dst_registry.write_text(
        _rewrite_localhost(registry_src.read_text(encoding="utf-8"), host_gateway),
        encoding="utf-8",
    )

    # Some agent folders carry editor-convenience symlinks/junctions back to
    # the project root (.agents, .knowledge-base, .system) so an editor opened
    # at the agent dir can still reach it - not agent content, and copytree
    # would otherwise follow them into a runaway recursive copy.
    dst_agent_dir = staging_dir / "agents" / agent
    shutil.copytree(
        _AGENTS_DIR / agent, dst_agent_dir,
        ignore=shutil.ignore_patterns(".agents", ".knowledge-base", ".system"),
    )
    agent_json = dst_agent_dir / "agent.json"
    if agent_json.exists():
        agent_json.write_text(
            _rewrite_localhost(agent_json.read_text(encoding="utf-8"), host_gateway),
            encoding="utf-8",
        )

    for rel in commit_scope:
        _copy_scope_dir(rel, staging_dir)
    for rel in set(state_allowlist) | set(state_readonly):
        _copy_state_file(rel, staging_dir)


def _write_run_dockerfile(
    staging_dir: Path,
    base_tag: str,
    agent: str,
    task_id: str,
    state_allowlist: list[str],
    state_readonly: list[str],
) -> None:
    # Own-agent state (agents/<agent>/**) and system/state/** are covered by
    # the blanket COPYs below. A cross-agent read (e.g. lore reading
    # agents/vision/state/processed-images.json) lives outside both and needs
    # its own explicit COPY line, or it's staged on the host but never makes
    # it into the image the agent actually runs against.
    own_prefix = f"agents/{agent}/"
    extra_copies = sorted(
        rel for rel in set(state_allowlist) | set(state_readonly)
        if not rel.startswith(own_prefix)
        and not rel.startswith("system/state/")
        and (staging_dir / rel).exists()
    )

    lines = [
        f"FROM {base_tag}\n",
        "WORKDIR /app\n",
        # Guards against sandbox-in-sandbox recursion (see
        # nexus.runtime.dispatch_config.running_inside_sandbox) - the staged
        # registry.yaml below still says sandbox.enabled: true for this
        # agent; this env var is what stops the inner runner from trying to
        # sandbox itself again (no docker/podman inside this container).
        "ENV NEXUS_SANDBOXED=1\n",
        "COPY agents/registry.yaml agents/registry.yaml\n",
        f"COPY agents/{agent} agents/{agent}\n",
        "COPY .knowledge-base .knowledge-base\n",
        "COPY system/state system/state\n",
    ]
    lines.extend(f"COPY {rel} {rel}\n" for rel in extra_copies)
    lines.append(f'CMD ["python", "-m", "nexus.runner", "--task", "{task_id}", "--force"]\n')

    (staging_dir / "Dockerfile").write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Base image - built once, cached, reused across runs
# ---------------------------------------------------------------------------

def _base_image_hash() -> str:
    h = hashlib.sha256()
    h.update((_PROJECT_ROOT / "pyproject.toml").read_bytes())
    src_dir = _PROJECT_ROOT / "system" / "src"
    for p in sorted(src_dir.rglob("*.py")):
        h.update(str(p.relative_to(src_dir)).encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _image_exists(runtime_bin: str, tag: str) -> bool:
    return subprocess.run(
        [runtime_bin, "image", "inspect", tag], capture_output=True
    ).returncode == 0


def _ensure_base_image(runtime_bin: str, log: Logger, *, rebuild: bool) -> str:
    tag = f"nexus-sandbox-base:{_base_image_hash()}"
    if not rebuild and _image_exists(runtime_bin, tag):
        log.info(f"reusing cached base image {tag}")
        return tag

    log.info(f"building base image {tag} (first build installs Pillow/deepface/tf-keras - can take minutes)")
    with tempfile.TemporaryDirectory(prefix="nexus-sandbox-base-") as tmp:
        tmp_path = Path(tmp)
        shutil.copy2(_PROJECT_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
        shutil.copytree(_PROJECT_ROOT / "system" / "src", tmp_path / "system" / "src")
        (tmp_path / "Dockerfile").write_text(_BASE_DOCKERFILE, encoding="utf-8")
        result = subprocess.run(
            [runtime_bin, "build", "-t", tag, str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise SandboxPreflightError(f"base image build failed:\n{result.stderr}")
    return tag


def _build_run_image(runtime_bin: str, staging_dir: Path, tag: str) -> None:
    result = subprocess.run(
        [runtime_bin, "build", "-t", tag, str(staging_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise SandboxPreflightError(f"image build failed for {tag}:\n{result.stderr}")


# ---------------------------------------------------------------------------
# Run + extract
# ---------------------------------------------------------------------------

def _run_container(
    runtime_bin: str, run_id: str, image_tag: str, env_forward: dict[str, str], gateway_ip: Optional[str]
) -> tuple[int, str]:
    cmd = [runtime_bin, "run", "--name", run_id]
    if runtime_bin == "podman":
        cmd.append(f"--add-host=host.containers.internal:{gateway_ip or 'host-gateway'}")
    for key, val in env_forward.items():
        cmd += ["-e", f"{key}={val}"]
    cmd.append(image_tag)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output


_EXTRACT_ROOTS = (".knowledge-base", "agents", "system/state")


def _extract(runtime_bin: str, run_id: str, after_dir: Path, log: Logger) -> None:
    after_dir.mkdir(parents=True, exist_ok=True)
    for rel in _EXTRACT_ROOTS:
        dst = after_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [runtime_bin, "cp", f"{run_id}:/app/{rel}", str(dst)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            log.warning(f"extract {rel} failed: {result.stderr.strip()}")


_CONTAINER_MASTER_LOG_REL = "agents/runtime/state/logs/automation.log"


def _forward_container_log(after_dir: Path, log: Logger) -> None:
    """Append the container's own automation.log onto the host's real one.

    The sandboxed agent's actual work (classify_images.py etc.) logs its
    '--- DONE (classified: N, failed: N) ---' line to *its own* container
    filesystem, not the host's - without this, nexus.runtime.metrics'
    parse_agent_items() would find nothing and every sandboxed run would
    silently record 0 processed/0 failed. This is pure log content, not a
    vault/state write, so it's forwarded unconditionally on apply (never on
    --dry-run, which must leave every real host path untouched).
    """
    container_log = after_dir / _CONTAINER_MASTER_LOG_REL
    if not container_log.exists():
        return
    try:
        content = container_log.read_text(encoding="utf-8")
    except Exception as exc:
        log.warning(f"could not read container automation.log for forwarding: {exc}")
        return
    if not content.strip():
        return
    _MASTER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_MASTER_LOG, "a", encoding="utf-8") as fh:
        fh.write(content)


def _cleanup(runtime_bin: str, container_name: str, image_tag: str, keep_image: bool) -> None:
    if keep_image:
        return
    subprocess.run([runtime_bin, "rm", container_name], capture_output=True)
    subprocess.run([runtime_bin, "rmi", image_tag], capture_output=True)


def _processed_item_uuid8(changes: list[dict], after_dir: Path, fm_io: FrontmatterIO) -> Optional[str]:
    """First 8 chars of the uuid: frontmatter field on the first changed
    knowledge-base markdown file - identifies which vault item this run
    actually processed, so the container's name is legible in `podman ps -a`
    without cross-referencing the run record."""
    for change in sorted(changes, key=lambda c: c["path"]):
        if change["class"] != "knowledge-base" or not change["path"].endswith(".md"):
            continue
        source = after_dir / change["path"]
        if not source.exists():
            continue
        try:
            fm, _ = fm_io.read(source)
        except Exception:
            continue
        uuid = fm.get("uuid")
        if uuid:
            return str(uuid)[:8]
    return None


def _rename_container(runtime_bin: str, run_id: str, new_name: str, log: Logger) -> str:
    """Best-effort: renames the running/finished container to new_name and
    returns whichever name is now correct to use for extract/cleanup."""
    result = subprocess.run(
        [runtime_bin, "rename", run_id, new_name], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        log.warning(f"container rename {run_id} -> {new_name} failed: {result.stderr.strip()}")
        return run_id
    return new_name


# ---------------------------------------------------------------------------
# Diff + classify
# ---------------------------------------------------------------------------

def _should_skip(relpath: str) -> bool:
    if relpath == "Dockerfile":  # synthesized by _write_run_dockerfile, not real repo content
        return True
    parts = relpath.split("/")
    if any(part in _SKIP_DIRNAMES for part in parts):
        return True
    return Path(relpath).suffix in _SKIP_SUFFIXES


def _walk_relpaths(root: Path) -> set[str]:
    if not root.exists():
        return set()
    out: set[str] = set()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if not _should_skip(rel):
            out.add(rel)
    return out


def _classify(
    relpath: str, commit_scope: list[str], state_allowlist: list[str], state_readonly: list[str]
) -> tuple[str, Optional[str]]:
    for scope in commit_scope:
        scope = scope.rstrip("/")
        if relpath == scope or relpath.startswith(scope + "/"):
            return "knowledge-base", None
    if relpath in state_allowlist:
        return "state", None
    if relpath in state_readonly:
        return "other", "read-only shared state"
    return "other", "outside declared commit_scope/state_files"


def _make_diff(relpath: str, before: bytes, after: bytes) -> tuple[bool, str]:
    try:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeDecodeError:
        return True, ""
    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=relpath, tofile=relpath,
        )
    )
    if len(diff_lines) > _DIFF_TRUNCATE_LINES:
        omitted = len(diff_lines) - _DIFF_TRUNCATE_LINES
        diff_lines = diff_lines[:_DIFF_TRUNCATE_LINES] + [f"... (truncated, {omitted} more lines)\n"]
    return False, "".join(diff_lines)


def _diff_and_classify(
    before_dir: Path,
    after_dir: Path,
    commit_scope: list[str],
    state_allowlist: list[str],
    state_readonly: list[str],
    allow_deletes: bool,
) -> list[dict]:
    before_files = _walk_relpaths(before_dir)
    after_files = _walk_relpaths(after_dir)
    changes: list[dict] = []

    for relpath in sorted(before_files | after_files):
        before_bytes = (before_dir / relpath).read_bytes() if relpath in before_files else b""
        after_bytes = (after_dir / relpath).read_bytes() if relpath in after_files else b""
        if before_bytes == after_bytes:
            continue

        is_delete = relpath in before_files and relpath not in after_files
        cls, reason = _classify(relpath, commit_scope, state_allowlist, state_readonly)

        if reason is not None:
            status = "dropped"
        elif is_delete:
            if cls == "knowledge-base" and allow_deletes:
                status, reason = "applied", None
            elif cls == "knowledge-base":
                status, reason = "dropped", "delete not enabled for this agent (sandbox.allow_deletes=false)"
            else:
                status, reason = "dropped", "state deletions are never applied"
        else:
            status = "applied"

        binary, diff_text = _make_diff(relpath, before_bytes, after_bytes)
        changes.append({
            "path": relpath,
            "class": cls,
            "status": status,
            "reason": reason,
            "binary": binary,
            "bytesBefore": len(before_bytes),
            "bytesAfter": len(after_bytes),
            "diff": diff_text,
        })
    return changes


# ---------------------------------------------------------------------------
# Apply - defense-in-depth vault_guard re-check, then write to real host paths
# ---------------------------------------------------------------------------

def _is_library_path(relpath: str) -> bool:
    return relpath == ".knowledge-base/02-Library" or relpath.startswith(".knowledge-base/02-Library/")


def _apply_changes(changes: list[dict], after_dir: Path, log: Logger) -> None:
    guard = VaultGuard(VaultPaths(vault_root=_VAULT_ROOT))
    fm_io = FrontmatterIO()

    with FileLock(_APPLY_LOCK):
        for change in changes:
            if change["status"] != "applied":
                continue
            relpath = change["path"]
            target = _PROJECT_ROOT / relpath
            source = after_dir / relpath

            try:
                if change["class"] == "knowledge-base":
                    if _is_library_path(relpath):
                        raise VaultWriteError(f"Agents may not write directly to 02-Library/: {relpath}")
                    if target.suffix == ".md" and source.exists():
                        fm, _ = fm_io.read(source)
                        guard.assert_not_self_approved(fm)

                if not source.exists():
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                log.info(f"applied {relpath}")
            except VaultWriteError as exc:
                change["status"] = "dropped"
                change["reason"] = str(exc)
                log.warning(f"dropped {relpath}: {exc}")


def _relabel_no_apply(changes: list[dict], exit_code: int, dry_run: bool) -> None:
    """Called when nothing gets applied (dry-run, or non-zero exit without --apply-on-failure)."""
    for change in changes:
        if change["status"] != "applied":
            if dry_run:
                change["status"] = "would-drop"
            continue
        if dry_run:
            change["status"] = "would-apply"
        else:
            change["status"] = "dropped"
            change["reason"] = f"container exited {exit_code}, apply_on_failure not set"


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------

def _write_record(record: dict) -> Path:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = _RUNS_DIR / f"{record['runId']}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(
    agent: str,
    *,
    dry_run: bool = False,
    allow_deletes_override: Optional[bool] = None,
    keep_image: bool = False,
    runtime_pref: Optional[str] = None,
    rebuild_base: bool = False,
    apply_on_failure: bool = False,
) -> int:
    log = _make_logger()
    t0 = log.start()

    if agent not in AGENT_NAME_TO_TASK:
        raise SandboxPreflightError(
            f"Unknown agent {agent!r}; must be one of {sorted(AGENT_NAME_TO_TASK)}"
        )
    task_id = AGENT_NAME_TO_TASK[agent]

    runtime_bin = _detect_runtime(runtime_pref)
    _preflight(runtime_bin)
    runtime_version = _runtime_version(runtime_bin)
    host_gateway = _host_gateway_name(runtime_bin)

    gateway_ip = _podman_wsl_gateway_ip() if runtime_bin == "podman" else None
    if runtime_bin == "podman":
        _warn_unreachable_llm_ports(
            (_AGENTS_DIR / "registry.yaml").read_text(encoding="utf-8"), gateway_ip, log
        )

    commit_scope, state_allowlist, state_readonly = _resolve_scopes(agent, task_id)
    if not commit_scope:
        log.warning(f"{agent} has an empty commit_scope - no knowledge-base changes will ever apply")
    allow_deletes = _allow_deletes(agent, allow_deletes_override)
    dispatch_type = _agent_json_dispatch_type(agent, task_id)

    env_forward: dict[str, str] = {}
    if dispatch_type == "claude-api":
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            if os.environ.get(key):
                env_forward[key] = os.environ[key]
        if not env_forward:
            raise SandboxPreflightError(
                f"{agent} uses claude-api dispatch but no ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN "
                "is set in this environment"
            )

    started_at = datetime.now(timezone.utc)
    ts = started_at.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"run-{ts}-{agent}"
    log.info(f"{run_id}: runtime={runtime_bin} dry_run={dry_run} allow_deletes={allow_deletes}")

    with tempfile.TemporaryDirectory(prefix=f"nexus-sandbox-{agent}-") as tmp:
        tmp_path = Path(tmp)
        staging_dir = tmp_path / "context"
        staging_dir.mkdir(parents=True)
        _stage_build_context(agent, commit_scope, state_allowlist, state_readonly, host_gateway, staging_dir)

        base_tag = _ensure_base_image(runtime_bin, log, rebuild=rebuild_base)
        _write_run_dockerfile(staging_dir, base_tag, agent, task_id, state_allowlist, state_readonly)

        image_tag = f"nexus-sandbox-{agent}-{ts}".lower()

        t_build0 = time.monotonic()
        _build_run_image(runtime_bin, staging_dir, image_tag)
        build_ms = int((time.monotonic() - t_build0) * 1000)

        t_run0 = time.monotonic()
        exit_code, container_log = _run_container(runtime_bin, run_id, image_tag, env_forward, gateway_ip)
        run_ms = int((time.monotonic() - t_run0) * 1000)
        log.info(f"{run_id}: container exited {exit_code} ({run_ms}ms)")

        after_dir = tmp_path / "after"
        _extract(runtime_bin, run_id, after_dir, log)

        changes = _diff_and_classify(
            staging_dir, after_dir, commit_scope, state_allowlist, state_readonly, allow_deletes
        )

        uuid8 = _processed_item_uuid8(changes, after_dir, FrontmatterIO())
        container_name = _rename_container(runtime_bin, run_id, f"agent-{agent}-{uuid8}", log) \
            if uuid8 else run_id

        should_apply = (not dry_run) and (exit_code == 0 or apply_on_failure)
        if should_apply:
            _apply_changes(changes, after_dir, log)
            _forward_container_log(after_dir, log)
        else:
            _relabel_no_apply(changes, exit_code, dry_run)

        _cleanup(runtime_bin, container_name, image_tag, keep_image)

    finished_at = datetime.now(timezone.utc)
    applied = sum(1 for c in changes if c["status"] == "applied")
    dropped = sum(1 for c in changes if c["status"] in ("dropped", "would-drop"))

    log_lines = container_log.splitlines()
    if len(log_lines) > _CONTAINER_LOG_TAIL_LINES:
        log_lines = log_lines[-_CONTAINER_LOG_TAIL_LINES:]

    record = {
        "runId": run_id,
        "containerName": container_name,
        "agent": agent,
        "taskId": task_id,
        "runtime": runtime_bin,
        "runtimeVersion": runtime_version,
        "baseImage": base_tag,
        "image": image_tag,
        "dispatchType": dispatch_type or "unknown",
        "startedAt": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finishedAt": finished_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "buildMs": build_ms,
        "runMs": run_ms,
        "containerExitCode": exit_code,
        "dryRun": dry_run,
        "allowDeletes": allow_deletes,
        "commitScope": commit_scope,
        "stateAllowlist": state_allowlist,
        "summary": {"changed": len(changes), "applied": applied, "dropped": dropped},
        "changes": changes,
        "containerLog": "\n".join(log_lines),
    }
    record_path = _write_record(record)

    log.done(t0, key="changed", count=len(changes), failed=0 if exit_code == 0 else 1)
    print(f"{run_id}: {applied} applied, {dropped} dropped, {len(changes)} total changed.")
    print(f"Record: {record_path}")

    return 0 if exit_code == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one nexus agent inside an isolated Podman/Docker container sandbox."
    )
    parser.add_argument("--agent", required=True, choices=sorted(AGENT_NAME_TO_TASK))
    parser.add_argument("--dry-run", action="store_true", help="Diff and record, apply nothing")
    parser.add_argument("--allow-deletes", dest="allow_deletes", action="store_true", default=None)
    parser.add_argument("--no-allow-deletes", dest="allow_deletes", action="store_false")
    parser.add_argument("--keep-image", action="store_true", help="Keep the per-run image+container")
    parser.add_argument("--runtime", choices=["podman", "docker"], default=None)
    parser.add_argument("--rebuild-base", action="store_true")
    parser.add_argument("--apply-on-failure", action="store_true")
    args = parser.parse_args()

    try:
        return run(
            args.agent,
            dry_run=args.dry_run,
            allow_deletes_override=args.allow_deletes,
            keep_image=args.keep_image,
            runtime_pref=args.runtime,
            rebuild_base=args.rebuild_base,
            apply_on_failure=args.apply_on_failure,
        )
    except SandboxPreflightError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
