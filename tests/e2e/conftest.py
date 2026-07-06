"""E2E conftest — sys.path bootstrap and shared cleanup fixture."""
import json
import sys
from pathlib import Path

import pytest

_AGENTS_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _AGENTS_DIR.parent
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

# Stable constants shared with test module
E2E_INBOX_SUBDIR = ".knowledge-base/00-Inbox/images/e2e-test"
E2E_IMAGE_NAME   = "e2e-mileena-mk.jpg"


def _do_cleanup(root: Path) -> None:
    """Remove all e2e test artifacts. Safe to call multiple times."""
    inbox_dir = root / E2E_INBOX_SUBDIR

    # Remove everything in e2e-test/ (original + renamed image + tokens)
    if inbox_dir.exists():
        for f in inbox_dir.iterdir():
            if f.is_file():
                f.unlink()
        try:
            inbox_dir.rmdir()
        except OSError:
            pass  # not empty — leave it

    # Remove inbox-queue.json entries in e2e-test/
    queue_file = root / "system" / "state" / "inbox-queue.json"
    if queue_file.exists():
        try:
            q = json.loads(queue_file.read_text(encoding="utf-8"))
            keys_to_remove = [k for k in q if "e2e-test" in k]
            for k in keys_to_remove:
                q.pop(k)
            if keys_to_remove:
                tmp = queue_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(q, indent=2), encoding="utf-8")
                tmp.replace(queue_file)
        except Exception:
            pass

    # Remove processed-images.json entries for e2e images
    proc_path = root / "agents" / "vision" / "state" / "processed-images.json"
    if proc_path.exists():
        try:
            state = json.loads(proc_path.read_text(encoding="utf-8"))
            images = state.get("images", {})
            path_index = state.get("pathIndex", {})
            keys_to_remove = [
                k for k, v in images.items()
                if isinstance(v, dict) and "e2e-test" in v.get("path", "")
            ]
            for k in keys_to_remove:
                path_val = images[k].get("path", "")
                images.pop(k, None)
                path_index.pop(path_val, None)
            if keys_to_remove:
                proc_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Remove 01-Processing/ entities that reference e2e-test images
    processing = root / ".knowledge-base" / "01-Processing"
    if processing.exists():
        for md in processing.glob("*.md"):
            try:
                content = md.read_text(encoding="utf-8")
                if "e2e-test" in content:
                    md.unlink()
            except Exception:
                pass

    # Remove processed-npcs.json entries for e2e images
    proc_npcs = root / "agents" / "lore" / "state" / "processed-npcs.json"
    if proc_npcs.exists():
        try:
            pn = json.loads(proc_npcs.read_text(encoding="utf-8"))
            sha_set = _e2e_sha_set(root)
            keys_to_remove = [k for k in pn if any(s in k for s in sha_set)]
            for k in keys_to_remove:
                pn.pop(k)
            if keys_to_remove:
                proc_npcs.write_text(json.dumps(pn, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Remove generated-tokens.json entries for e2e images
    gen_tokens = root / "agents" / "token" / "state" / "generated-tokens.json"
    if gen_tokens.exists():
        try:
            gt = json.loads(gen_tokens.read_text(encoding="utf-8"))
            keys_to_remove = [
                k for k, v in gt.items()
                if isinstance(v, dict) and "e2e-test" in v.get("sourcePath", "")
            ]
            for k in keys_to_remove:
                gt.pop(k)
            if keys_to_remove:
                gen_tokens.write_text(json.dumps(gt, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Remove classification bad-docs.txt entries for e2e images
    bad_docs = root / "agents" / "classification" / "state" / "bad-docs.txt"
    if bad_docs.exists():
        try:
            lines = bad_docs.read_text(encoding="utf-8").splitlines()
            kept  = [ln for ln in lines if "e2e-test" not in ln]
            if len(kept) != len(lines):
                bad_docs.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except Exception:
            pass


def _e2e_sha_set(root: Path) -> set[str]:
    """Return sha256 keys from processed-images.json that belong to e2e-test."""
    proc_path = root / "agents" / "vision" / "state" / "processed-images.json"
    if not proc_path.exists():
        return set()
    try:
        state = json.loads(proc_path.read_text(encoding="utf-8"))
        return {
            k for k, v in state.get("images", {}).items()
            if isinstance(v, dict) and "e2e-test" in v.get("path", "")
        }
    except Exception:
        return set()


@pytest.fixture(scope="module")
def project_root() -> Path:
    return _PROJECT_ROOT


@pytest.fixture(scope="module", autouse=True)
def cleanup_e2e_artifacts():
    """Pre-clean (fresh state) and post-clean (remove artifacts).

    Set E2E_KEEP_ARTIFACTS=1 to skip post-cleanup so artifacts stay visible
    on the dashboard for manual inspection.
    """
    import os
    _do_cleanup(_PROJECT_ROOT)  # always pre-clean for a fresh run
    yield
    if os.environ.get("E2E_KEEP_ARTIFACTS") == "1":
        print("\n[e2e] E2E_KEEP_ARTIFACTS=1 — artifacts preserved for dashboard inspection")
        return
    _do_cleanup(_PROJECT_ROOT)
