"""
E2E test: upload an image through the dashboard's upload-image API and confirm
it lands in 00-Inbox/ and the ingestion pipeline (running daemon/runner)
picks it up into inbox-queue.json within a timeout.

Requires:
  - Dashboard dev server running (system/dashboard, `npm run dev`, port 48080)
  - A runner/daemon polling ingestion-agent on its normal interval (this test
    does not dispatch the agent itself — it waits for whatever is running)

Run:
  pytest agents/tests/e2e/test_dashboard_upload_e2e.py -v -m e2e

Keep the uploaded file after test:
  E2E_KEEP_ARTIFACTS=1 pytest agents/tests/e2e/test_dashboard_upload_e2e.py -v -m e2e
"""
from __future__ import annotations

import io
import os
import time
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.e2e

_AGENTS_DIR   = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _AGENTS_DIR.parent
_VAULT_ROOT   = _PROJECT_ROOT / "knowledge-base"
_INBOX_DIR    = _VAULT_ROOT / "00-Inbox" / "images" / "e2e-upload"

_DASHBOARD_BASE = "http://localhost:48080"
IMAGE_NAME      = "e2e-upload-test.png"
POLL_TIMEOUT_S  = 120
POLL_INTERVAL_S = 3

# 1x1 PNG — smallest valid image, no network download needed.
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


def test_upload_image_and_wait_for_inbox_queue():
    target_path = f"knowledge-base/00-Inbox/images/e2e-upload/{IMAGE_NAME}"

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

    deadline = time.monotonic() + POLL_TIMEOUT_S
    found = False
    while time.monotonic() < deadline:
        q = requests.get(f"{_DASHBOARD_BASE}/api/queue", timeout=10).json()
        items = {item["path"]: item for item in q.get("items", [])}
        if target_path in items:
            found = True
            break
        time.sleep(POLL_INTERVAL_S)

    assert found, (
        f"{target_path!r} did not appear in inbox-queue.json within {POLL_TIMEOUT_S}s "
        "— is the ingestion agent's daemon/runner running?"
    )
