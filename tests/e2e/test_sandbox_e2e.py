"""
E2E test: nexus.tasks.sandbox_run against a real Podman/Docker container.

tests/test_sandbox_run.py deliberately mocks subprocess.run for every
container-runtime call (see its module docstring) - it covers scope
resolution, classification, and apply-time guards, but never actually
builds or runs a container. This test fills that gap: it drives the real
CLI entrypoint and asserts on the real run record, so a regression in the
build/run/extract/cleanup plumbing (e.g. the WSL host-gateway resolution,
or the container-rename-by-processed-uuid logic) fails a test instead of
only surfacing during a manual QA pass.

Uses --dry-run so nothing is ever written back to the real vault/state,
and doesn't require LM Studio to be reachable - the vision agent no-ops
cleanly (WARN + exit 0) when its LLM is offline, which is itself a valid
and already-covered code path. What this test actually validates is the
container orchestration around it.

Requires:
  - Podman or Docker on PATH, daemon/machine running (`<runtime> info` succeeds)

Run: pytest tests/e2e/test_sandbox_e2e.py -v -m e2e
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RUNS_DIR = _PROJECT_ROOT / "system" / "state" / "sandbox" / "runs"

_CONTAINER_NAME_RE = re.compile(r"^(run-\d{8}T\d{6}Z-vision|agent-vision-[0-9a-fA-F]{8})$")


def _detect_runtime() -> str | None:
    for name in ("podman", "docker"):
        if not shutil.which(name):
            continue
        if subprocess.run([name, "info"], capture_output=True).returncode == 0:
            return name
    return None


@pytest.fixture(scope="module")
def runtime() -> str:
    rt = _detect_runtime()
    if rt is None:
        pytest.skip("no running podman/docker found on PATH")
    return rt


def _run_record_names() -> set[str]:
    if not _RUNS_DIR.exists():
        return set()
    return {p.name for p in _RUNS_DIR.glob("run-*-vision.json")}


def _latest_new_record(before: set[str]) -> dict:
    new = sorted(_run_record_names() - before)
    assert new, "sandbox_run did not write a new run record under system/state/sandbox/runs/"
    return json.loads((_RUNS_DIR / new[-1]).read_text(encoding="utf-8"))


def test_sandbox_run_vision_dry_run_builds_and_runs_container(runtime):
    before = _run_record_names()

    result = subprocess.run(
        [sys.executable, "-m", "nexus.tasks.sandbox_run", "--agent", "vision", "--dry-run"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600,
    )
    assert result.returncode in (0, 2), (
        f"sandbox_run crashed unexpectedly (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    record = _latest_new_record(before)

    assert record["runtime"] == runtime
    assert record["dryRun"] is True
    assert record["containerExitCode"] == 0, "vision agent's own container should exit 0 even with its LLM offline"
    assert record["summary"]["applied"] == 0, "a dry-run must never apply a change"
    assert _CONTAINER_NAME_RE.match(record["containerName"]), (
        f"unexpected container name shape: {record['containerName']!r}"
    )

    for change in record["changes"]:
        if change["status"] in ("dropped", "would-drop"):
            assert change["reason"], f"dropped change missing a reason: {change['path']}"
        if change["class"] == "knowledge-base":
            assert change["path"].startswith(".knowledge-base/"), change["path"]

    # cleanup: no leftover container/image after a non---keep-image run
    ps = subprocess.run(
        [runtime, "ps", "-a", "--filter", f"name={record['containerName']}", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    assert record["containerName"] not in ps.stdout.split(), "container was not cleaned up"

    images = subprocess.run(
        [runtime, "images", record["image"], "--format", "{{.Repository}}"],
        capture_output=True, text=True,
    )
    assert images.stdout.strip() == "", "per-run image was not cleaned up"
