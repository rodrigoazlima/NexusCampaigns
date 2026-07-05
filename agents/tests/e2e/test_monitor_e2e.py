"""
Monitoring test: drop image in inbox and observe pipeline state changes.

Downloads Versus2mileenamk32.png (MK3 Mileena) to 00-Inbox, runs ingestion
and vision agents, then asserts state files reflect each stage correctly.

Run:
  pytest agents/tests/e2e/test_monitor_e2e.py -v -m e2e

Keep artifacts after test:
  E2E_KEEP_ARTIFACTS=1 pytest agents/tests/e2e/test_monitor_e2e.py -v -m e2e
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AGENTS_DIR   = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _AGENTS_DIR.parent
_RUNNER_PY    = _AGENTS_DIR / "runtime" / "tools" / "runner.py"

_VAULT_ROOT  = _PROJECT_ROOT / ".knowledge-base"
_INBOX_DIR   = _VAULT_ROOT   / "00-Inbox" / "images" / "e2e-monitor"
_PROCESSING  = _VAULT_ROOT   / "01-Processing"
_QUEUE_FILE  = _PROJECT_ROOT / "system"  / "state"  / "inbox-queue.json"
_PROC_IMAGES = _AGENTS_DIR   / "vision"   / "state"  / "processed-images.json"

IMAGE_URL  = (
    "https://static.wikia.nocookie.net/mortalkombat/images/6/6a/"
    "Versus2mileenamk32.png/revision/latest?cb=20100528155327&path-prefix=es"
)
IMAGE_NAME = "e2e-monitor-mileena-mk3.png"
MARKER     = "e2e-monitor"

LLM_TIMEOUT = 600


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_agent(task_id: str, timeout: int = LLM_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_RUNNER_PY), "--task", task_id, "--once", "--force"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def _queue_key() -> str | None:
    if not _QUEUE_FILE.exists():
        return None
    q = _read_json(_QUEUE_FILE)
    for k in q:
        if MARKER in k:
            return k
    return None


def _vision_entry() -> dict | None:
    if not _PROC_IMAGES.exists():
        return None
    state = _read_json(_PROC_IMAGES)
    for entry in state.get("images", {}).values():
        if MARKER in entry.get("path", ""):
            return entry
    return None


def _draft_file() -> Path | None:
    if not _PROCESSING.exists():
        return None
    for md in sorted(_PROCESSING.glob("*.md")):
        try:
            if MARKER in md.read_text(encoding="utf-8"):
                return md
        except Exception:
            pass
    return None


def _detect_and_delete_image():
    """Delete inbox image if present so stage1 always downloads fresh."""
    img = _INBOX_DIR / IMAGE_NAME
    if img.exists():
        print(f"\n[monitor] Stale image found — deleting {img.name} for fresh start")
        img.unlink()


def _cleanup_state():
    """Clean queue entries, processed-images (images + pathIndex), and drafts.

    Inbox image is preserved so the user can inspect it on the dashboard.
    """
    # Remove inbox-queue entries (key may be original or renamed path after vision)
    if _QUEUE_FILE.exists():
        q = _read_json(_QUEUE_FILE)
        cleaned = {k: v for k, v in q.items() if MARKER not in k}
        _QUEUE_FILE.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")

    # Remove processed-images entries AND their pathIndex pointers
    if _PROC_IMAGES.exists():
        state      = _read_json(_PROC_IMAGES)
        images     = state.get("images", {})
        path_index = state.get("pathIndex", {})
        bad_shas   = [k for k, v in images.items() if MARKER in v.get("path", "")]
        for sha in bad_shas:
            bad_path = images[sha].get("path", "")
            images.pop(sha, None)
            path_index.pop(bad_path, None)
        state["images"]    = images
        state["pathIndex"] = path_index
        _PROC_IMAGES.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # Remove 01-Processing drafts referencing this marker
    if _PROCESSING.exists():
        for md in list(_PROCESSING.glob("*.md")):
            try:
                if MARKER in md.read_text(encoding="utf-8"):
                    md.unlink()
            except Exception:
                pass


@pytest.fixture(scope="module", autouse=True)
def cleanup_monitor_artifacts():
    _detect_and_delete_image()  # fresh start: remove stale inbox image
    _cleanup_state()            # clean pipeline state
    yield
    _cleanup_state()            # post-test: clean state only, image kept
    print(f"\n[monitor] Image preserved — view at http://localhost:3131/gm/review")


# ---------------------------------------------------------------------------
# Stage 1 — Download
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_stage1_download():
    """Download MK3 Mileena versus screen PNG to 00-Inbox/images/e2e-monitor/."""
    _INBOX_DIR.mkdir(parents=True, exist_ok=True)
    img_path = _INBOX_DIR / IMAGE_NAME

    resp = requests.get(IMAGE_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    img_path.write_bytes(resp.content)

    assert img_path.exists(), "Image not saved"
    assert img_path.stat().st_size > 5_000, f"Image too small ({img_path.stat().st_size} bytes)"

    # Accept PNG, JPEG, or WebP
    header = img_path.read_bytes()[:12]
    is_jpeg = header[:2] == b"\xff\xd8"
    is_png  = header[:4] == b"\x89PNG"
    is_webp = header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    assert is_jpeg or is_png or is_webp, (
        f"Not a valid image — magic bytes: {header[:4].hex()}"
    )
    print(f"\n[monitor] Downloaded {img_path.stat().st_size:,} bytes → {img_path.name}")


# ---------------------------------------------------------------------------
# Stage 2 — Ingestion: image enters pipeline queue
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_stage2_ingestion():
    """Ingestion agent registers image in inbox-queue.json with vision=pending."""
    img_path = _INBOX_DIR / IMAGE_NAME
    assert img_path.exists(), "Run test_stage1 first"

    result = _run_agent("ingestion-agent", timeout=60)
    assert result.returncode == 0, (
        f"ingestion-agent failed (exit {result.returncode})\n{result.stdout[-2000:]}"
    )

    assert _QUEUE_FILE.exists(), "inbox-queue.json not created"
    queue = _read_json(_QUEUE_FILE)
    img_rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
    assert img_rel in queue, (
        f"Image not in inbox-queue.\nExpected key: {img_rel!r}\nFound keys: {list(queue)[:8]}"
    )

    agents = queue[img_rel].get("agents", {})
    assert agents.get("vision") == "pending", (
        f"vision should be pending after ingestion, got: {agents}"
    )
    print(f"\n[monitor] Queue entry: {agents}")


# ---------------------------------------------------------------------------
# Stage 3 — Vision: image classified, draft written to 01-Processing/
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_stage3_vision():
    """Vision agent classifies image via LM Studio and writes draft to 01-Processing/."""
    key = _queue_key()
    assert key is not None, "Run test_stage2 first"

    result = _run_agent("vision-agent", timeout=LLM_TIMEOUT)

    combined = result.stdout + result.stderr
    if "LLMOfflineError" in combined or "unreachable" in combined.lower():
        pytest.fail(
            "LM Studio not running on localhost:1234 — start it with a vision model first."
        )

    assert result.returncode == 0, (
        f"vision-agent failed (exit {result.returncode})\n{result.stdout[-3000:]}"
    )

    # processed-images.json must have an entry for this image
    entry = _vision_entry()
    assert entry is not None, (
        f"No entry for {MARKER} in processed-images.json after vision"
    )
    print(f"\n[monitor] Vision result: status={entry.get('status')!r} type={entry.get('type')!r}")

    assert entry.get("status") == "ok", f"Vision entry status: {entry.get('status')!r}"
    assert entry.get("type") not in (None, "unknown"), (
        f"Vision did not classify image type: {entry.get('type')!r}"
    )

    # Draft must exist in 01-Processing/
    draft = _draft_file()
    assert draft is not None, "No draft entity written to 01-Processing/ after vision"
    print(f"[monitor] Draft created: {draft.name}")

    content = draft.read_text(encoding="utf-8")
    assert "status: draft" in content, "Draft missing 'status: draft'"
    assert "reviewed: false" in content, "Draft missing 'reviewed: false'"

    # Queue updated — vision renames the file to its canonical slug and
    # rekeys the queue entry to match (see classify_images.py step 10), so
    # re-resolve the marker-matched key rather than reusing the pre-rename one.
    queue     = _read_json(_QUEUE_FILE)
    final_key = _queue_key()
    assert final_key is not None and final_key in queue, (
        f"no queue entry for {MARKER} found after vision rename (was {key!r})"
    )
    assert queue[final_key]["agents"].get("vision") == "done", (
        f"vision slot not marked done: {queue[final_key]['agents']}"
    )


# ---------------------------------------------------------------------------
# Stage 4 — Review readiness: draft present, not yet in library
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_stage4_review_readiness():
    """Draft entity is present, in draft status, and not yet promoted to 02-Library."""
    draft = _draft_file()
    assert draft is not None, "No draft entity found — run test_stage3 first"

    content = draft.read_text(encoding="utf-8")
    assert "status: draft" in content
    assert "reviewed: false" in content

    library_copy = _VAULT_ROOT / "02-Library" / draft.name
    assert not library_copy.exists(), (
        f"Draft already in 02-Library — human review was bypassed: {library_copy}"
    )

    print(f"\n[monitor] Entity ready for review: {draft.name}")
    print(f"[monitor] Dashboard: http://localhost:3131/gm/review")
