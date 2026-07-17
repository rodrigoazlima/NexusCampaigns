"""Tests for nexus.workers.token - agent-token.spec.md compliance."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# sys.path is bootstrapped by conftest.py
# "token" collides with stdlib token module - import via file path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _PROJECT_ROOT / "system" / "src" / "nexus" / "workers" / "token.py"
_spec = importlib.util.spec_from_file_location("token_generate_tokens", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["token_generate_tokens"] = mod
_spec.loader.exec_module(mod)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vision_state_ok(tmp_path: Path) -> dict:
    """A minimal processed-images.json with two eligible portraits."""
    return {
        "version": 2,
        "images": {
            "abc123": {
                "path": ".knowledge-base/00-Inbox/images/A1/hero.png",
                "processedAt": "2026-06-01T00:00:00Z",
                "originalName": "hero.png",
                "type": "portrait",
                "ancestry": "human",
                "class": "fighter",
                "creature_type": "humanoid",
                "element": "none",
                "environment": "dungeon",
                "description": "A brave fighter",
                "sha256": "abc123",
                "isToken": False,
                "status": "ok",
            },
            "def456": {
                "path": ".knowledge-base/00-Inbox/images/A1/mage.png",
                "processedAt": "2026-06-01T00:00:00Z",
                "originalName": "mage.png",
                "type": "body",
                "ancestry": "elf",
                "class": "wizard",
                "creature_type": "humanoid",
                "element": "none",
                "environment": "none",
                "description": "An elven wizard",
                "sha256": "def456",
                "isToken": False,
                "status": "ok",
            },
            "bmap99": {
                "path": ".knowledge-base/00-Inbox/images/A1/dungeon-map.png",
                "processedAt": "2026-06-01T00:00:00Z",
                "originalName": "dungeon-map.png",
                "type": "battlemap",
                "ancestry": "none",
                "class": "none",
                "creature_type": "none",
                "element": "none",
                "environment": "dungeon",
                "description": "",
                "sha256": "bmap99",
                "isToken": False,
                "status": "ok",
            },
            "tok111": {
                "path": ".knowledge-base/00-Inbox/images/A1/hero-token.png",
                "processedAt": "2026-06-01T00:00:00Z",
                "originalName": "hero-token.png",
                "type": "portrait",
                "ancestry": "human",
                "class": "none",
                "creature_type": "none",
                "element": "none",
                "environment": "none",
                "description": "",
                "sha256": "tok111",
                "isToken": True,
                "status": "ok",
            },
        },
        "pathIndex": {
            ".knowledge-base/00-Inbox/images/A1/hero.png":  "abc123",
            ".knowledge-base/00-Inbox/images/A1/mage.png":  "def456",
            ".knowledge-base/00-Inbox/images/A1/dungeon-map.png": "bmap99",
            ".knowledge-base/00-Inbox/images/A1/hero-token.png":  "tok111",
        },
    }


@pytest.fixture
def gen_tokens_partial() -> dict:
    """generated-tokens.json with hero already done."""
    return {
        "abc123": {
            "sourcePath":  ".knowledge-base/00-Inbox/images/A1/hero.png",
            "tokenPath":   ".knowledge-base/00-Inbox/images/A1/hero-token.png",
            "generatedAt": "2026-06-01T00:00:00Z",
        }
    }


# ---------------------------------------------------------------------------
# _load_vision_state
# ---------------------------------------------------------------------------

class TestLoadVisionState:
    def test_returns_empty_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_VISION_STATE", tmp_path / "processed-images.json")
        result = mod._load_vision_state()
        assert result == {"images": {}, "pathIndex": {}}

    def test_reads_existing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vision_state_ok: dict) -> None:
        p = tmp_path / "processed-images.json"
        p.write_text(json.dumps(vision_state_ok), encoding="utf-8")
        monkeypatch.setattr(mod, "_VISION_STATE", p)
        result = mod._load_vision_state()
        assert "abc123" in result["images"]


# ---------------------------------------------------------------------------
# _load_gen_tokens / _save_gen_tokens
# ---------------------------------------------------------------------------

class TestGenTokensIO:
    def test_returns_empty_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        assert mod._load_gen_tokens() == {}

    def test_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        data = {"sha1": {"sourcePath": "a", "tokenPath": "b", "generatedAt": "2026-01-01"}}
        mod._save_gen_tokens(data)
        assert mod._load_gen_tokens() == data

    def test_atomic_write_uses_tmp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save must use tmp → replace (no partial writes)."""
        out = tmp_path / "generated-tokens.json"
        monkeypatch.setattr(mod, "_GEN_TOKENS", out)
        mod._save_gen_tokens({"key": {"sourcePath": "x", "tokenPath": "y", "generatedAt": "z"}})
        assert out.exists()
        assert not (tmp_path / "generated-tokens.tmp").exists()


# ---------------------------------------------------------------------------
# Eligible image filtering (mirrors main() logic)
# ---------------------------------------------------------------------------

class TestEligibleFilter:
    """Unit-test the filtering logic used in main() and list_pending_portraits."""

    def _eligible(self, vision_state: dict, gen_tokens: dict) -> list[tuple[str, dict]]:
        return [
            (k, e)
            for k, e in vision_state.get("images", {}).items()
            if e.get("status") == "ok"
            if not e.get("isToken", False)
            if e.get("type") not in mod._SKIP_TYPES
            if k not in gen_tokens
        ]

    def test_excludes_battlemap(self, vision_state_ok: dict) -> None:
        eligible = self._eligible(vision_state_ok, {})
        keys = {k for k, _ in eligible}
        assert "bmap99" not in keys

    def test_excludes_istoken(self, vision_state_ok: dict) -> None:
        eligible = self._eligible(vision_state_ok, {})
        keys = {k for k, _ in eligible}
        assert "tok111" not in keys

    def test_excludes_already_generated(self, vision_state_ok: dict, gen_tokens_partial: dict) -> None:
        eligible = self._eligible(vision_state_ok, gen_tokens_partial)
        keys = {k for k, _ in eligible}
        assert "abc123" not in keys
        assert "def456" in keys

    def test_includes_portrait_and_body(self, vision_state_ok: dict) -> None:
        eligible = self._eligible(vision_state_ok, {})
        keys = {k for k, _ in eligible}
        assert "abc123" in keys  # portrait
        assert "def456" in keys  # body

    def test_excludes_failed_status(self, vision_state_ok: dict) -> None:
        vision_state_ok["images"]["abc123"]["status"] = "failed"
        eligible = self._eligible(vision_state_ok, {})
        keys = {k for k, _ in eligible}
        assert "abc123" not in keys


# ---------------------------------------------------------------------------
# _upper_center_crop
# ---------------------------------------------------------------------------

class TestUpperCenterCrop:
    def test_returns_four_ints(self) -> None:
        x, y, s, _ = mod._upper_center_crop(200, 400, {})
        assert isinstance(x, int)
        assert isinstance(y, int)
        assert isinstance(s, int)

    def test_crop_within_bounds(self) -> None:
        w, h = 300, 400
        x, y, s, _ = mod._upper_center_crop(w, h, {})
        assert x >= 0 and x + s <= w
        assert y >= 0


# ---------------------------------------------------------------------------
# handle() must not lie about when a token was produced (QA finding #1):
# the exists-shortcut branch skips _make_token() entirely, so generatedAt
# must come from the file's own mtime, not datetime.now().
# ---------------------------------------------------------------------------

class TestHandleGeneratedAtIntegrity:
    def test_skip_branch_uses_file_mtime_not_now(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "10-generate-tokens.json")
        monkeypatch.setattr(mod, "_QUEUE_FILE", tmp_path / "inbox-queue.json")
        monkeypatch.setattr(mod, "_VISION_STATE", tmp_path / "processed-images.json")
        monkeypatch.setattr(mod, "_LEGACY_STATE_DIRS", ())

        img_path = tmp_path / "hero.png"
        img_path.write_bytes(b"fake")
        out_path = tmp_path / "hero-token.png"
        out_path.write_bytes(b"fake-token")

        old_ts = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
        os.utime(out_path, (old_ts, old_ts))

        worker = mod.TokenWorker()
        item = mod.WorkItem("hero.png", {
            "action": "generate",
            "img_key": "abc123",
            "entry": {"processedAt": "2026-07-01T00:00:00Z"},
            "stale": False,
        })

        result = worker.handle(item)
        assert result.status == "done"

        entry = mod._load_gen_tokens()["abc123"]
        assert entry["generatedAt"] == datetime.fromtimestamp(old_ts, tz=timezone.utc).isoformat()
        assert "lastVerifiedAt" in entry
        assert entry["sourceProcessedAt"] == "2026-07-01T00:00:00Z"


# ---------------------------------------------------------------------------
# pending() must invalidate a token when its source is reclassified after
# generation (QA finding #3), but stay hands-off on a human-paused slot
# (QA finding #4's pin mechanism).
# ---------------------------------------------------------------------------

class TestStaleTokenDetection:
    _SRC_REL = "00-Inbox/images/hero.png"

    def _vision_state(self) -> dict:
        return {
            "images": {
                "abc123": {
                    "path": self._SRC_REL,
                    "processedAt": "2026-07-01T00:00:00Z",
                    "type": "portrait",
                    "isToken": False,
                    "status": "ok",
                }
            },
            "pathIndex": {self._SRC_REL: "abc123"},
        }

    def _gen_tokens_stale(self) -> dict:
        return {
            "abc123": {
                "sourcePath": self._SRC_REL,
                "tokenPath": "00-Inbox/images/hero-token.png",
                "generatedAt": "2026-06-01T00:00:00Z",
                "sourceProcessedAt": "2026-06-01T00:00:00Z",  # older than vision's processedAt above
            }
        }

    def _worker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queue: dict) -> "mod.TokenWorker":
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "10-generate-tokens.json")
        monkeypatch.setattr(mod, "_LEGACY_STATE_DIRS", ())
        monkeypatch.setattr(mod, "_load_vision_state", lambda: self._vision_state())
        monkeypatch.setattr(mod, "_load_gen_tokens", lambda: self._gen_tokens_stale())
        monkeypatch.setattr(mod, "_load_queue", lambda: queue)

        src = tmp_path / self._SRC_REL
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")
        # Existing token file so the unrelated "purge stale index entry" scan
        # (tokenPath missing on disk) doesn't also fire here.
        (tmp_path / "00-Inbox" / "images" / "hero-token.png").write_bytes(b"fake-token")

        return mod.TokenWorker()

    def test_flags_stale_as_generate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # classification must be settled (done/skip) for pending() to emit a
        # 'generate' item at all - staleness is orthogonal to that gate.
        queue = {self._SRC_REL: {"agents": {"classification": "done"}}}
        worker = self._worker(tmp_path, monkeypatch, queue=queue)
        items = worker.pending()

        generate_items = [i for i in items if i.payload.get("action") == "generate"]
        assert len(generate_items) == 1
        assert generate_items[0].payload["stale"] is True

    def test_paused_slot_skips_stale_check(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        queue = {self._SRC_REL: {"agents": {"token": "paused"}}}
        worker = self._worker(tmp_path, monkeypatch, queue=queue)
        items = worker.pending()

        assert items == []


# ---------------------------------------------------------------------------
# Logger integration - DONE line uses "generated" keyword
# ---------------------------------------------------------------------------

class TestLoggerDoneFormat:
    def test_done_uses_generated_keyword(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from nexus.shared.logger import Logger

        logs_dir = tmp_path / "logs"
        master = tmp_path / "auto.log"
        log = Logger(
            task_id="token-agent",
            script_basename="generate_tokens.py",
            logs_dir=logs_dir,
            master_log=master,
        )
        t0 = log.start()
        log.done(t0, key="generated", count=5, failed=1)

        content = master.read_text(encoding="utf-8")
        assert "generated: 5" in content
        assert "failed: 1" in content
        assert "--- DONE" in content


# ---------------------------------------------------------------------------
# pending() must wait for classification (not just vision) before generating.
# ---------------------------------------------------------------------------

class TestClassificationGate:
    """pending() must wait for the classification slot before emitting a
    'generate' WorkItem - vision-done alone is no longer sufficient."""

    _SRC_REL = "00-Inbox/images/hero.png"

    def _vision_state(self, entry_type: str = "portrait") -> dict:
        return {
            "images": {
                "abc123": {
                    "path": self._SRC_REL,
                    "processedAt": "2026-07-01T00:00:00Z",
                    "type": entry_type,
                    "isToken": False,
                    "status": "ok",
                }
            },
            "pathIndex": {self._SRC_REL: "abc123"},
        }

    def _worker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queue: dict,
               gen_tokens: dict | None = None, entry_type: str = "portrait") -> "mod.TokenWorker":
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "10-generate-tokens.json")
        monkeypatch.setattr(mod, "_LEGACY_STATE_DIRS", ())
        monkeypatch.setattr(mod, "_load_vision_state", lambda: self._vision_state(entry_type))
        monkeypatch.setattr(mod, "_load_gen_tokens", lambda: gen_tokens or {})
        monkeypatch.setattr(mod, "_load_queue", lambda: queue)

        src = tmp_path / self._SRC_REL
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        return mod.TokenWorker()

    @staticmethod
    def _generate_items(items: list) -> list:
        return [i for i in items if i.payload.get("action") == "generate"]

    def test_blocks_generate_when_classification_pending(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        queue = {self._SRC_REL: {"agents": {"classification": "pending"}}}
        worker = self._worker(tmp_path, monkeypatch, queue)
        assert self._generate_items(worker.pending()) == []

    def test_allows_generate_when_classification_done(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        queue = {self._SRC_REL: {"agents": {"classification": "done"}}}
        worker = self._worker(tmp_path, monkeypatch, queue)
        assert len(self._generate_items(worker.pending())) == 1

    def test_allows_generate_when_classification_skip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        queue = {self._SRC_REL: {"agents": {"classification": "skip"}}}
        worker = self._worker(tmp_path, monkeypatch, queue)
        assert len(self._generate_items(worker.pending())) == 1

    def test_skip_type_battlemap_not_blocked_by_classification(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        queue = {self._SRC_REL: {"agents": {"token": "pending", "classification": "pending"}}}
        worker = self._worker(tmp_path, monkeypatch, queue, entry_type="battlemap")
        items = worker.pending()
        actions = {i.payload.get("action") for i in items}
        assert "skip-type" in actions
        assert self._generate_items(items) == []

    def test_reconcile_not_blocked_by_classification(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        queue = {self._SRC_REL: {"agents": {"token": "pending", "classification": "pending"}}}
        gen_tokens = {"abc123": {"sourcePath": self._SRC_REL, "tokenPath": self._SRC_REL,
                                  "sourceProcessedAt": "2026-07-01T00:00:00Z"}}
        worker = self._worker(tmp_path, monkeypatch, queue, gen_tokens=gen_tokens)
        items = worker.pending()
        actions = {i.payload.get("action") for i in items}
        assert "reconcile" in actions


# ---------------------------------------------------------------------------
# _resolve_entity_type / _find_draft / _note_type_index
# ---------------------------------------------------------------------------

class TestResolveEntityType:
    def test_prefers_note_type_over_vision_entity_type(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_PROCESSING", tmp_path)
        mod.FrontmatterIO().write(
            tmp_path / "dragon.md",
            {"type": "monster", "source": ["00-Inbox/images/dragon.png"]},
            "body",
        )
        result = mod._resolve_entity_type("00-Inbox/images/dragon.png", {"entity_type": "npc"})
        assert result == "monster"

    def test_falls_back_to_vision_entity_type_when_no_note(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_PROCESSING", tmp_path)
        result = mod._resolve_entity_type("00-Inbox/images/dragon.png", {"entity_type": "npc"})
        assert result == "npc"

    def test_falls_back_to_none_when_nothing_resolves(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_PROCESSING", tmp_path)
        result = mod._resolve_entity_type("00-Inbox/images/dragon.png", {})
        assert result == "none"

    def test_uses_note_type_cache_when_provided(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(rel_img: str) -> None:
            raise AssertionError("_find_draft should not be called when a cache is provided")

        monkeypatch.setattr(mod, "_find_draft", _boom)
        result = mod._resolve_entity_type("x.png", {}, note_type_cache={"x.png": "creature"})
        assert result == "creature"


class TestNoteTypeIndex:
    def test_builds_source_to_type_map(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_PROCESSING", tmp_path)
        io_ = mod.FrontmatterIO()
        io_.write(tmp_path / "a.md", {"type": "monster", "source": ["a.png"]}, "body")
        io_.write(tmp_path / "b.md", {"type": "item", "source": ["b.png"]}, "body")
        index = mod._note_type_index()
        assert index == {"a.png": "monster", "b.png": "item"}

    def test_skips_notes_without_type(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_PROCESSING", tmp_path)
        mod.FrontmatterIO().write(tmp_path / "notype.md", {"source": ["c.png"]}, "body")
        assert mod._note_type_index() == {}

    def test_empty_when_processing_dir_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_PROCESSING", tmp_path / "does-not-exist")
        assert mod._note_type_index() == {}


# ---------------------------------------------------------------------------
# _locate_face routing
# ---------------------------------------------------------------------------

class TestLocateFace:
    _ARR = np.zeros((10, 10, 3), dtype=np.uint8)

    def test_item_bucket_skips_face_detection_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(arr: object) -> None:
            raise AssertionError("face detector should not be called for the item bucket")

        monkeypatch.setattr(mod, "_detect_face_mtcnn", _boom)
        monkeypatch.setattr(mod, "_detect_face_opencv", _boom)
        monkeypatch.setattr(mod, "_detect_face_monster", _boom)
        assert mod._locate_face("item", self._ARR) is None

    def test_monster_bucket_routes_to_monster_detector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(arr: object) -> None:
            raise AssertionError("humanoid detectors should not be called for the monster bucket")

        monkeypatch.setattr(mod, "_detect_face_mtcnn", _boom)
        monkeypatch.setattr(mod, "_detect_face_opencv", _boom)
        monkeypatch.setattr(mod, "_detect_face_monster", lambda arr: (1, 2, 3, 4))
        assert mod._locate_face("monster", self._ARR) == (1, 2, 3, 4)

    def test_humanoid_bucket_uses_mtcnn_then_opencv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_detect_face_mtcnn", lambda arr: None)
        monkeypatch.setattr(mod, "_detect_face_opencv", lambda arr: (5, 6, 7, 8))
        assert mod._locate_face("npc", self._ARR) == (5, 6, 7, 8)

    def test_unknown_type_defaults_to_humanoid_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_detect_face_mtcnn", lambda arr: None)
        monkeypatch.setattr(mod, "_detect_face_opencv", lambda arr: (5, 6, 7, 8))
        assert mod._locate_face("faction", self._ARR) == (5, 6, 7, 8)


# ---------------------------------------------------------------------------
# _detect_face_monster
# ---------------------------------------------------------------------------

class TestDetectFaceMonster:
    def test_returns_none_on_blank_image(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_HAAR_CASCADE", None)
        arr = np.zeros((200, 200, 3), dtype=np.uint8)
        assert mod._detect_face_monster(arr) is None

    def test_picks_largest_not_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _FakeCascade:
            def detectMultiScale(self, gray, scaleFactor, minNeighbors, minSize):
                return [(10, 10, 20, 20), (50, 50, 80, 80)]

        monkeypatch.setattr(mod, "_HAAR_CASCADE", None)
        monkeypatch.setattr(cv2, "CascadeClassifier", lambda path: _FakeCascade())
        arr = np.zeros((200, 200, 3), dtype=np.uint8)
        result = mod._detect_face_monster(arr)
        assert result == (90, 90, 80, 80)


# ---------------------------------------------------------------------------
# _saliency_bbox / _saliency_center / _locate_region_center
# ---------------------------------------------------------------------------

def _contrasting_square_array() -> np.ndarray:
    """200x200 dark background with an 80x80 bright square centered at (100,100)."""
    arr = np.zeros((200, 200, 3), dtype=np.uint8)
    arr[60:140, 60:140] = 255
    return arr


class TestSaliencyBbox:
    def test_finds_bbox_on_contrasting_square(self) -> None:
        bbox = mod._saliency_bbox(_contrasting_square_array())
        assert bbox is not None
        bx, by, bw, bh = bbox
        cx, cy = bx + bw // 2, by + bh // 2
        assert abs(cx - 100) <= 30
        assert abs(cy - 100) <= 30

    def test_returns_none_on_flat_image(self) -> None:
        arr = np.full((200, 200, 3), 128, dtype=np.uint8)
        assert mod._saliency_bbox(arr) is None


class TestSaliencyCenter:
    def test_returns_padded_square_around_blob_centroid(self) -> None:
        arr = _contrasting_square_array()
        result = mod._saliency_center(arr, 200, 200)
        assert result is not None
        x, y, size, size2 = result
        assert size == size2
        cx, cy = x + size // 2, y + size // 2
        assert abs(cx - 100) <= 30
        assert abs(cy - 100) <= 30

    def test_returns_none_when_saliency_bbox_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_saliency_bbox", lambda arr: None)
        assert mod._saliency_center(_contrasting_square_array(), 200, 200) is None


class TestLocateRegionCenter:
    def test_uses_saliency_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(w: int, h: int, cfg: dict) -> None:
            raise AssertionError("static fallback should not be used when saliency succeeds")

        monkeypatch.setattr(mod, "_saliency_center", lambda arr, w, h: (1, 2, 3, 4))
        monkeypatch.setattr(mod, "_upper_center_crop", _boom)
        result = mod._locate_region_center(_contrasting_square_array(), 200, 200, {})
        assert result == (1, 2, 3, 4)

    def test_falls_back_to_static_when_saliency_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_saliency_center", lambda arr, w, h: None)
        result = mod._locate_region_center(_contrasting_square_array(), 200, 200, {})
        assert result == mod._upper_center_crop(200, 200, {})


# ---------------------------------------------------------------------------
# _make_token entity_type routing
# ---------------------------------------------------------------------------

class TestMakeTokenEntityTypeRouting:
    def test_passes_entity_type_to_locate_face(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from nexus.shared.logger import Logger

        calls: list[str] = []
        monkeypatch.setattr(mod, "_locate_face", lambda entity_type, arr: calls.append(entity_type) or None)
        monkeypatch.setattr(mod, "_locate_region_center", lambda arr, w, h, cfg: (0, 0, 50, 50))

        src = tmp_path / "src.png"
        Image.new("RGB", (100, 100), color=(10, 20, 30)).save(str(src), "PNG")
        out = tmp_path / "out-token.png"
        log = Logger(task_id="token", script_basename="token", logs_dir=tmp_path / "logs",
                    master_log=tmp_path / "auto.log")

        ok, face = mod._make_token(src, out, {}, log, moldura_path=None, entity_type="item")
        assert calls == ["item"]
        assert ok is True


# ---------------------------------------------------------------------------
# TokenWorker._note_type_cache laziness
# ---------------------------------------------------------------------------

class TestNoteTypeCacheLaziness:
    """The note-type reverse index is built at most once per TokenWorker
    lifetime, lazily, only when actual generation is needed."""

    def _worker(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> "mod.TokenWorker":
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_CONFIG_FILE", tmp_path / "10-generate-tokens.json")
        monkeypatch.setattr(mod, "_QUEUE_FILE", tmp_path / "inbox-queue.json")
        monkeypatch.setattr(mod, "_LEGACY_STATE_DIRS", ())
        monkeypatch.setattr(mod, "_load_vision_state", lambda: {})
        monkeypatch.setattr(mod, "_load_gen_tokens", lambda: {})
        monkeypatch.setattr(mod, "_load_queue", lambda: {})
        monkeypatch.setattr(mod, "_set_queue_token_slot", lambda *a, **k: True)
        return mod.TokenWorker()

    def test_cache_built_once_per_worker_lifetime(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []
        monkeypatch.setattr(mod, "_note_type_index", lambda: calls.append(1) or {})
        monkeypatch.setattr(mod, "_make_token", lambda *a, **k: (True, None))

        for name in ("hero.png", "villain.png"):
            (tmp_path / name).write_bytes(b"fake")

        worker = self._worker(tmp_path, monkeypatch)

        for name in ("hero.png", "villain.png"):
            item = mod.WorkItem(name, {
                "action": "generate", "img_key": f"key-{name}",
                "entry": {"processedAt": "2026-07-01T00:00:00Z"}, "stale": False,
            })
            result = worker.handle(item)
            assert result.status == "done"

        assert len(calls) == 1

    def test_cache_not_built_when_token_already_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []
        monkeypatch.setattr(mod, "_note_type_index", lambda: calls.append(1) or {})

        (tmp_path / "hero.png").write_bytes(b"fake")
        (tmp_path / "hero-token.png").write_bytes(b"fake-token")

        worker = self._worker(tmp_path, monkeypatch)
        item = mod.WorkItem("hero.png", {
            "action": "generate", "img_key": "abc",
            "entry": {"processedAt": "2026-07-01T00:00:00Z"}, "stale": False,
        })
        result = worker.handle(item)

        assert result.status == "done"
        assert calls == []
