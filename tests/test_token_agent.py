"""Tests for nexus.tasks.generate_tokens — agent-token.spec.md compliance."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path is bootstrapped by conftest.py
# "token" collides with stdlib token module — import via file path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _PROJECT_ROOT / "system" / "src" / "nexus" / "tasks" / "generate_tokens.py"
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
        monkeypatch.setattr(mod, "_AGENT_STATE", tmp_path)
        assert mod._load_gen_tokens() == {}

    def test_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_AGENT_STATE", tmp_path)
        data = {"sha1": {"sourcePath": "a", "tokenPath": "b", "generatedAt": "2026-01-01"}}
        mod._save_gen_tokens(data)
        assert mod._load_gen_tokens() == data

    def test_atomic_write_uses_tmp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save must use tmp → replace (no partial writes)."""
        out = tmp_path / "generated-tokens.json"
        monkeypatch.setattr(mod, "_GEN_TOKENS", out)
        monkeypatch.setattr(mod, "_AGENT_STATE", tmp_path)
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
# Logger integration — DONE line uses "generated" keyword
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
