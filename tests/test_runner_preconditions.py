"""runner._inbox_has_slot must skip queue entries whose file no longer exists
on disk — otherwise a renamed/deleted/overwritten source keeps the entry
'pending' forever and the runner dispatches against it every due cycle."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_RUNNER_PATH = (
    Path(__file__).resolve().parents[1] / "system" / "src" / "nexus" / "runner.py"
)


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("runner_under_test_precond", _RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runner_under_test_precond"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner(tmp_path):
    mod = _load_runner_module()
    mod._PROJECT_ROOT = tmp_path
    mod._INBOX_QUEUE = tmp_path / "system" / "state" / "inbox-queue.json"
    mod._INBOX_QUEUE.parent.mkdir(parents=True)
    return mod


def _write_queue(runner, entries: dict) -> None:
    runner._INBOX_QUEUE.write_text(json.dumps(entries), encoding="utf-8")


def test_skips_pending_entry_whose_file_is_gone(runner):
    _write_queue(runner, {
        "00-Inbox/images/gone.body.jpg": {"agents": {"vision": "pending"}},
    })

    assert runner._inbox_has_slot("vision") is False


def test_counts_pending_entry_whose_file_exists(runner):
    img = runner._PROJECT_ROOT / "00-Inbox" / "images" / "here.body.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"fake")
    _write_queue(runner, {
        "00-Inbox/images/here.body.jpg": {"agents": {"vision": "pending"}},
    })

    assert runner._inbox_has_slot("vision") is True


def test_valid_entry_still_counts_alongside_a_stale_one(runner):
    img = runner._PROJECT_ROOT / "00-Inbox" / "images" / "here.body.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"fake")
    _write_queue(runner, {
        "00-Inbox/images/gone.body.jpg": {"agents": {"vision": "pending"}},
        "00-Inbox/images/here.body.jpg": {"agents": {"vision": "pending"}},
    })

    assert runner._inbox_has_slot("vision") is True
