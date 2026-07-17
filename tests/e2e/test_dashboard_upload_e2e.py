"""
E2E test: upload an image through the dashboard's upload-image API and confirm
the ingestion agent picks it up into inbox-queue.json.

ingestion-agent's registry interval is 3600s, so a passively-polling daemon
won't re-run it inside any reasonable test window. Force-dispatch it via
runner.py (same convention as test_pipeline_e2e.py / test_monitor_e2e.py)
rather than waiting on the background schedule.

Requires:
  - Dashboard server running (system/dashboard, port 48080)
  - ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN set (runner dispatches agents
    via claude-api tool-use even for LLM-less agents like ingestion)

Run:
  pytest agents/tests/e2e/test_dashboard_upload_e2e.py -v -m e2e

Keep the uploaded file after test:
  E2E_KEEP_ARTIFACTS=1 pytest agents/tests/e2e/test_dashboard_upload_e2e.py -v -m e2e
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.e2e

_PROJECT_ROOT   = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _PROJECT_ROOT / "agents"
_RUNNER_PY    = _PROJECT_ROOT / "system" / "src" / "nexus" / "runner.py"
_VAULT_ROOT   = _PROJECT_ROOT / ".knowledge-base"
_INBOX_DIR    = _VAULT_ROOT / "00-Inbox" / "images" / "e2e-upload"
_QUEUE_FILE   = _PROJECT_ROOT / "system" / "state" / "inbox-queue.json"

_DASHBOARD_BASE = "http://localhost:48080"
IMAGE_NAME      = "e2e-upload-test.png"

# 1x1 PNG - smallest valid image, no network download needed.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415478da6360606060000000050001a5f645400000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    if os.environ.get("E2E_KEEP_ARTIFACTS"):
        return
    img_path = _INBOX_DIR / IMAGE_NAME
    if img_path.exists():
        img_path.unlink()
    try:
        _INBOX_DIR.rmdir()
    except OSError:
        pass


def test_upload_image_and_ingest_into_queue():
    target_path = f".knowledge-base/00-Inbox/images/e2e-upload/{IMAGE_NAME}"

    resp = requests.post(
        f"{_DASHBOARD_BASE}/api/gm/upload-image",
        files={"file": (IMAGE_NAME, io.BytesIO(_PNG_BYTES), "image/png")},
        data={"targetPath": target_path},
        timeout=10,
    )
    assert resp.status_code == 200, f"upload failed ({resp.status_code}): {resp.text[:300]}"
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("path") == target_path

    img_path = _PROJECT_ROOT / target_path
    assert img_path.exists(), "uploaded file not written to disk"

    result = subprocess.run(
        [sys.executable, str(_RUNNER_PY), "--task", "ingestion-agent", "--once", "--force"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, (
        f"ingestion-agent dispatch failed (exit {result.returncode})\n{result.stdout[-2000:]}"
    )

    assert _QUEUE_FILE.exists(), "inbox-queue.json not created"
    queue = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    assert target_path in queue, (
        f"{target_path!r} not registered in inbox-queue.json after ingestion-agent ran"
    )
    assert queue[target_path]["agents"]["vision"] == "pending"

    q = requests.get(f"{_DASHBOARD_BASE}/api/queue", timeout=10).json()
    items = {item["path"]: item for item in q.get("items", [])}
    assert target_path in items, f"{target_path!r} not visible via /api/queue"
