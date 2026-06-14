"""
E2E test: Mileena MK image through the full agent pipeline via runner.py.

Requires:
  - LM Studio running on localhost:1234 with a vision model loaded
  - Pillow, numpy (for token generation)

Pipeline stages:
  1. Download  — JPEG lands in 00-Inbox/images/e2e-test/
  2. Ingestion — runner dispatches ingestion_agent.py → inbox-queue.json updated
  3. Vision    — runner dispatches classify_images.py → LM Studio classifies,
                 renames image, writes draft to 01-Processing/
  4. Lore      — runner dispatches generate_npcs.py → NPC sheet written to 01-Processing/
  5. Token     — runner dispatches generate_tokens.py → token PNG created
  6. Review    — draft entity in 01-Processing/ flagged for human review

Run normally (auto-cleanup):
  pytest .agents/tests/e2e/test_pipeline_e2e.py -v

Keep artifacts on dashboard after test:
  E2E_KEEP_ARTIFACTS=1 pytest .agents/tests/e2e/test_pipeline_e2e.py -v
"""
from __future__ import annotations

import io
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

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_INBOX_DIR   = _VAULT_ROOT   / "00-Inbox" / "images" / "e2e-test"
_PROCESSING  = _VAULT_ROOT   / "01-Processing"
_QUEUE_FILE  = _PROJECT_ROOT / ".system"  / "state"  / "inbox-queue.json"
_PROC_IMAGES = _AGENTS_DIR   / "vision"   / "state"  / "processed-images.json"
_GEN_TOKENS  = _AGENTS_DIR   / "token"    / "state"  / "generated-tokens.json"

IMAGE_URL  = (
    "https://static.wikia.nocookie.net/mortal-kombat/images/6/6e/"
    "Mileenaretrorender.jpg/revision/latest?cb=20130130220824&path-prefix=pt-br"
)
IMAGE_NAME = "e2e-mileena-mk.jpg"

# Timeout for LLM-backed agents (vision / lore can take several minutes)
LLM_AGENT_TIMEOUT = 600


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_agent(task_id: str, timeout: int = LLM_AGENT_TIMEOUT) -> subprocess.CompletedProcess:
    """Dispatch one agent via runner.py --force (bypass due-time + preconditions)."""
    return subprocess.run(
        [sys.executable, str(_RUNNER_PY),
         "--task", task_id, "--once", "--force"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def _e2e_inbox_key() -> str | None:
    """Return the inbox-queue key for the e2e image (may be renamed after vision)."""
    if not _QUEUE_FILE.exists():
        return None
    q = _read_json(_QUEUE_FILE)
    for k in q:
        if "e2e-test" in k:
            return k
    return None


def _find_e2e_draft() -> Path | None:
    """Find the 01-Processing/ draft that references the e2e-test image."""
    if not _PROCESSING.exists():
        return None
    for md in _PROCESSING.glob("*.md"):
        try:
            if "e2e-test" in md.read_text(encoding="utf-8"):
                return md
        except Exception:
            pass
    return None


def _find_e2e_vision_entry() -> dict | None:
    """Return the processed-images entry for the e2e image."""
    if not _PROC_IMAGES.exists():
        return None
    state = _read_json(_PROC_IMAGES)
    for entry in state.get("images", {}).values():
        if "e2e-test" in entry.get("path", ""):
            return entry
    return None


# ---------------------------------------------------------------------------
# Stage 1 — Download
# ---------------------------------------------------------------------------

def test_stage1_download():
    """Download Mileena image to 00-Inbox/images/e2e-test/ as a valid JPEG."""
    from PIL import Image as PILImage

    _INBOX_DIR.mkdir(parents=True, exist_ok=True)
    img_path = _INBOX_DIR / IMAGE_NAME

    resp = requests.get(IMAGE_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    raw = resp.content

    # Convert to true JPEG — wikia may serve WebP regardless of URL extension.
    # The dashboard image API uses file extension for Content-Type, so must be real JPEG.
    magic = raw[:2]
    if magic != b"\xff\xd8":
        img = PILImage.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        img_path.write_bytes(buf.getvalue())
    else:
        img_path.write_bytes(raw)

    assert img_path.exists()
    assert img_path.stat().st_size > 10_000, "Image too small — download failed"
    assert img_path.read_bytes()[:2] == b"\xff\xd8", "Not a valid JPEG"


# ---------------------------------------------------------------------------
# Stage 2 — Ingestion
# ---------------------------------------------------------------------------

def test_stage2_ingestion():
    """ingestion_agent.py registers image in inbox-queue.json with all slots pending."""
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
        f"Image not in inbox-queue. Expected: {img_rel!r}\nKeys: {list(queue)[:5]}"
    )

    agents = queue[img_rel].get("agents", {})
    assert agents.get("vision") == "pending", (
        f"vision slot should be pending after ingestion, got: {agents}"
    )


# ---------------------------------------------------------------------------
# Stage 3 — Vision classification
# ---------------------------------------------------------------------------

def test_stage3_vision():
    """classify_images.py classifies image via LM Studio, writes draft to 01-Processing/."""
    assert _QUEUE_FILE.exists(), "Run test_stage2 first"

    result = _run_agent("vision-agent", timeout=LLM_AGENT_TIMEOUT)

    # LM Studio offline → clear failure
    combined = result.stdout + result.stderr
    if "LLMOfflineError" in combined or "unreachable" in combined.lower():
        pytest.fail(
            "LM Studio is not running on localhost:1234. "
            "Start LM Studio with a vision model before running e2e tests."
        )

    assert result.returncode == 0, (
        f"vision-agent failed (exit {result.returncode})\n{result.stdout[-2000:]}"
    )

    # processed-images.json must have an entry for the e2e image
    entry = _find_e2e_vision_entry()
    assert entry is not None, "No e2e entry in processed-images.json after vision"
    assert entry.get("status") == "ok", f"Vision entry not ok: {entry.get('status')}"
    assert entry.get("type") not in (None, "unknown"), (
        f"Vision did not classify image type: {entry.get('type')}"
    )

    # Draft entity must exist in 01-Processing/
    draft = _find_e2e_draft()
    assert draft is not None, "No draft entity in 01-Processing/ referencing e2e-test image"

    content = draft.read_text(encoding="utf-8")
    assert "status: draft" in content
    assert "reviewed: false" in content

    # inbox-queue must mark vision as done
    queue = _read_json(_QUEUE_FILE)
    key = _e2e_inbox_key()
    assert key is not None, "e2e image not found in inbox-queue after vision"
    assert queue[key]["agents"].get("vision") == "done", (
        f"vision slot not done in inbox-queue: {queue[key]['agents']}"
    )


# ---------------------------------------------------------------------------
# Stage 4 — Lore (NPC sheet generation)
# ---------------------------------------------------------------------------

def test_stage4_lore():
    """generate_npcs.py enriches draft with NPC content from LM Studio."""
    entry = _find_e2e_vision_entry()
    assert entry is not None, "Run test_stage3 first"

    # Check scenarios exist — lore agent needs at least one active scenario
    scenarios_file = _AGENTS_DIR / "lore" / "state" / "scenarios.json"
    if not scenarios_file.exists():
        pytest.skip("No scenarios.json — lore agent has nothing to generate against")

    scenarios = _read_json(scenarios_file)
    active = [s for s in (scenarios if isinstance(scenarios, list) else scenarios.values())
              if s.get("active", True)]
    if not active:
        pytest.skip("No active scenarios — lore agent skipped")

    result = _run_agent("lore-agent", timeout=LLM_AGENT_TIMEOUT)

    combined = result.stdout + result.stderr
    if "LLMOfflineError" in combined or "unreachable" in combined.lower():
        pytest.fail("LM Studio offline — cannot run lore-agent")

    assert result.returncode == 0, (
        f"lore-agent failed (exit {result.returncode})\n{result.stdout[-2000:]}"
    )

    # Draft should now have NPC content (name, traits, etc.)
    draft = _find_e2e_draft()
    assert draft is not None, "Draft entity missing after lore"

    content = draft.read_text(encoding="utf-8")
    # Lore agent writes PF2e NPC fields
    assert any(kw in content for kw in ("name:", "traits:", "## Background", "## Personality")), (
        "Draft entity missing NPC content after lore agent"
    )


# ---------------------------------------------------------------------------
# Stage 5 — Token generation
# ---------------------------------------------------------------------------

def test_stage5_token():
    """generate_tokens.py creates a circular portrait token PNG."""
    entry = _find_e2e_vision_entry()
    assert entry is not None, "Run test_stage3 first"

    img_rel = entry.get("path", "")
    img_path = _PROJECT_ROOT / img_rel
    assert img_path.exists(), f"Source image not found at {img_rel}"

    result = _run_agent("token-agent", timeout=120)

    combined = result.stdout + result.stderr
    if "Pillow not installed" in combined or "ImportError" in combined:
        pytest.skip("Pillow/numpy not installed — token generation skipped")

    assert result.returncode == 0, (
        f"token-agent failed (exit {result.returncode})\n{result.stdout[-2000:]}"
    )

    # Token file created next to source image
    token_path = img_path.with_name(f"{img_path.stem}-token.png")
    assert token_path.exists(), (
        f"Token not found at {token_path}\nagent output: {result.stdout[-1000:]}"
    )

    # Valid PNG
    assert token_path.read_bytes()[:4] == b"\x89PNG", "Token is not a valid PNG"
    assert token_path.stat().st_size > 1_000, "Token file suspiciously small"

    # generated-tokens.json updated
    assert _GEN_TOKENS.exists(), "generated-tokens.json not created"


# ---------------------------------------------------------------------------
# Stage 6 — Human review flag
# ---------------------------------------------------------------------------

def test_stage6_review_flag():
    """Draft entity in 01-Processing/ must be ready for human review."""
    draft = _find_e2e_draft()
    assert draft is not None, (
        "No draft entity found in 01-Processing/ referencing e2e-test image. "
        "Run test_stage3 first."
    )

    content = draft.read_text(encoding="utf-8")
    assert "status: draft" in content, "Entity not in draft status"
    assert "reviewed: false" in content, "Entity not flagged for human review"

    # Must NOT be in 02-Library yet (requires human approval)
    library_copy = _VAULT_ROOT / "02-Library" / draft.name
    assert not library_copy.exists(), (
        "Entity already promoted to 02-Library — human review bypassed"
    )

    print(f"\n[e2e] Draft entity ready for review: {draft.name}")
    print(f"[e2e] View at: http://localhost:3131/gm/review")
