"""nexus.runtime.preconditions.inbox_has_slot must skip queue entries whose
file no longer exists on disk — otherwise a renamed/deleted/overwritten
source keeps the entry 'pending' forever and the runner dispatches against
it every due cycle."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "system" / "src" / "nexus" / "runtime" / "preconditions.py"
)


def _load_preconditions_module():
    spec = importlib.util.spec_from_file_location(
        "nexus.runtime._preconditions_under_test", _MODULE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nexus.runtime._preconditions_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner(tmp_path):
    mod = _load_preconditions_module()
    mod.PROJECT_ROOT = tmp_path
    mod.INBOX_QUEUE = tmp_path / "system" / "state" / "inbox-queue.json"
    mod.INBOX_QUEUE.parent.mkdir(parents=True)
    return mod


def _write_queue(runner, entries: dict) -> None:
    runner.INBOX_QUEUE.write_text(json.dumps(entries), encoding="utf-8")


def test_skips_pending_entry_whose_file_is_gone(runner):
    _write_queue(runner, {
        "00-Inbox/images/gone.body.jpg": {"agents": {"vision": "pending"}},
    })

    assert runner.inbox_has_slot("vision") is False


def test_counts_pending_entry_whose_file_exists(runner):
    img = runner.PROJECT_ROOT / "00-Inbox" / "images" / "here.body.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"fake")
    _write_queue(runner, {
        "00-Inbox/images/here.body.jpg": {"agents": {"vision": "pending"}},
    })

    assert runner.inbox_has_slot("vision") is True


def test_valid_entry_still_counts_alongside_a_stale_one(runner):
    img = runner.PROJECT_ROOT / "00-Inbox" / "images" / "here.body.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"fake")
    _write_queue(runner, {
        "00-Inbox/images/gone.body.jpg": {"agents": {"vision": "pending"}},
        "00-Inbox/images/here.body.jpg": {"agents": {"vision": "pending"}},
    })

    assert runner.inbox_has_slot("vision") is True


def test_vision_skips_non_image_extension(runner):
    """A mislabeled/misrouted queue entry pointing at a non-image file must
    not trigger a vision dispatch — vision can never do anything with it."""
    doc = runner.PROJECT_ROOT / "00-Inbox" / "docs" / "notes.txt"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"not an image")
    _write_queue(runner, {
        "00-Inbox/docs/notes.txt": {"agents": {"vision": "pending"}},
    })

    assert runner.inbox_has_slot("vision") is False


def test_vision_skips_zero_byte_file(runner):
    """A zero-byte placeholder (e.g. mid-copy) must not trigger a dispatch
    that would feed the vision LLM an empty/undecodable image."""
    img = runner.PROJECT_ROOT / "00-Inbox" / "images" / "empty.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"")
    _write_queue(runner, {
        "00-Inbox/images/empty.jpg": {"agents": {"vision": "pending"}},
    })

    assert runner.inbox_has_slot("vision") is False


def test_non_vision_slot_counts_non_image_document(runner):
    """lore/classification/wiki entries legitimately point at documents too
    (state-files.spec.md) — the extension filter is vision-only."""
    doc = runner.PROJECT_ROOT / "00-Inbox" / "docs" / "notes.txt"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"lore fodder")
    _write_queue(runner, {
        "00-Inbox/docs/notes.txt": {"agents": {"classification": "pending"}},
    })

    assert runner.inbox_has_slot("classification") is True
