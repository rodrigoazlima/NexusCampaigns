You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.system/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.system/config/<script_name>.json`)
     - Contains script-specific settings and overrides.
     - Always loaded after global config (can override global values).
     - Can be empty (`{}`) but must always exist.

2. **Output Format:**
   - You must output **two valid JSON objects** clearly labeled.
   - Use sensible, descriptive keys in `snake_case`.
   - Include meaningful `default` values for every setting.
   - Add a `"description"` field for each major setting when helpful.
   - Group related settings under logical sections if needed.

3. **What to Extract:**
   - Hardcoded paths (especially those derived from `__file__`)
   - Constants (BATCH_SIZE, thresholds, limits, etc.)
   - LLM settings (URL, model, provider, etc.)
   - File/directory references
   - Magic numbers and strings that are likely to change
   - Any environment-dependent behavior

4. **Rules:**
   - Prefer putting common things (project roots, LLM config, logging, shared directories) in **global**.
   - Put script-specific behavior (batch sizes, task-specific prompts, agent name, etc.) in **local**.
   - Make sure the JSONs contain good defaults so the script works even if the files are deleted.
   - Use clear, consistent naming.
   - Do not include code - only configuration.

---

**Script to analyze:**

# tests\test_token_agent.py
"""Tests for token.tools.generate_tokens - agent-token.spec.md compliance."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path is bootstrapped by conftest.py
# "token" collides with stdlib token module - import via file path
# ---------------------------------------------------------------------------

_AGENTS_DIR = Path(__file__).resolve().parents[1]
_MOD_PATH = _AGENTS_DIR / "token" / "tools" / "generate_tokens.py"
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
                "path": "knowledge-base/00-Inbox/images/A1/hero.png",
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
                "path": "knowledge-base/00-Inbox/images/A1/mage.png",
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
                "path": "knowledge-base/00-Inbox/images/A1/dungeon-map.png",
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
                "path": "knowledge-base/00-Inbox/images/A1/hero-token.png",
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
            "knowledge-base/00-Inbox/images/A1/hero.png":  "abc123",
            "knowledge-base/00-Inbox/images/A1/mage.png":  "def456",
            "knowledge-base/00-Inbox/images/A1/dungeon-map.png": "bmap99",
            "knowledge-base/00-Inbox/images/A1/hero-token.png":  "tok111",
        },
    }


@pytest.fixture
def gen_tokens_partial() -> dict:
    """generated-tokens.json with hero already done."""
    return {
        "abc123": {
            "sourcePath":  "knowledge-base/00-Inbox/images/A1/hero.png",
            "tokenPath":   "knowledge-base/00-Inbox/images/A1/hero-token.png",
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
# call_tool - list_pending_portraits
# ---------------------------------------------------------------------------

class TestCallToolListPendingPortraits:
    def test_returns_json_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vision_state_ok: dict) -> None:
        p = tmp_path / "processed-images.json"
        p.write_text(json.dumps(vision_state_ok), encoding="utf-8")
        monkeypatch.setattr(mod, "_VISION_STATE", p)
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_AGENT_STATE", tmp_path)

        result = mod.call_tool("list_pending_portraits", {}, {"project_root": str(tmp_path)})
        paths = json.loads(result)
        assert isinstance(paths, list)
        # only portrait/body images; not battlemap, not tokens
        assert all("dungeon-map" not in p for p in paths)
        assert all("hero-token" not in p for p in paths)

    def test_excludes_already_in_gen_tokens(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        vision_state_ok: dict,
        gen_tokens_partial: dict,
    ) -> None:
        p = tmp_path / "processed-images.json"
        p.write_text(json.dumps(vision_state_ok), encoding="utf-8")
        g = tmp_path / "generated-tokens.json"
        g.write_text(json.dumps(gen_tokens_partial), encoding="utf-8")
        monkeypatch.setattr(mod, "_VISION_STATE", p)
        monkeypatch.setattr(mod, "_GEN_TOKENS", g)
        monkeypatch.setattr(mod, "_AGENT_STATE", tmp_path)

        result = mod.call_tool("list_pending_portraits", {}, {"project_root": str(tmp_path)})
        paths = json.loads(result)
        # hero already in gen_tokens → must not appear
        assert not any("hero.png" in p and "token" not in p for p in paths)


# ---------------------------------------------------------------------------
# call_tool - generate_token (SHA256 key lookup)
# ---------------------------------------------------------------------------

class TestCallToolGenerateToken:
    def test_saves_with_sha256_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        vision_state_ok: dict,
    ) -> None:
        # create a real 1×1 PNG so Pillow can open it
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        img_dir = tmp_path / "knowledge-base" / "00-Inbox" / "images" / "A1"
        img_dir.mkdir(parents=True)
        img_path = img_dir / "hero.png"
        Image.new("RGBA", (100, 100), (200, 100, 50, 255)).save(str(img_path))

        p = tmp_path / "processed-images.json"
        # update vision_state paths to use tmp_path
        rel = "knowledge-base/00-Inbox/images/A1/hero.png"
        vision_state_ok["pathIndex"][rel] = "abc123"
        p.write_text(json.dumps(vision_state_ok), encoding="utf-8")

        monkeypatch.setattr(mod, "_VISION_STATE", p)
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_AGENT_STATE", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path / "logs")
        monkeypatch.setattr(mod, "_MASTER_LOG", tmp_path / "automation.log")

        result = mod.call_tool(
            "generate_token",
            {"image_path": str(img_path)},
            {"project_root": str(tmp_path)},
        )

        assert "hero" in result
        gen = json.loads((tmp_path / "generated-tokens.json").read_text(encoding="utf-8"))
        # key must be the SHA256 from pathIndex, not the path string
        assert "abc123" in gen

    def test_falls_back_to_path_key_when_not_in_index(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        vision_state_ok: dict,
    ) -> None:
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        img_dir = tmp_path / "knowledge-base" / "00-Inbox" / "images" / "A1"
        img_dir.mkdir(parents=True)
        img_path = img_dir / "unknown.png"
        Image.new("RGBA", (100, 100), (10, 20, 30, 255)).save(str(img_path))

        # vision state has no entry for unknown.png
        p = tmp_path / "processed-images.json"
        p.write_text(json.dumps(vision_state_ok), encoding="utf-8")

        monkeypatch.setattr(mod, "_VISION_STATE", p)
        monkeypatch.setattr(mod, "_GEN_TOKENS", tmp_path / "generated-tokens.json")
        monkeypatch.setattr(mod, "_AGENT_STATE", tmp_path)
        monkeypatch.setattr(mod, "_PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path / "logs")
        monkeypatch.setattr(mod, "_MASTER_LOG", tmp_path / "automation.log")

        mod.call_tool(
            "generate_token",
            {"image_path": str(img_path)},
            {"project_root": str(tmp_path)},
        )

        gen = json.loads((tmp_path / "generated-tokens.json").read_text(encoding="utf-8"))
        # fallback key starts with "path:"
        assert any(k.startswith("path:") for k in gen)


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
# Logger integration - DONE line uses "generated" keyword
# ---------------------------------------------------------------------------

class TestLoggerDoneFormat:
    def test_done_uses_generated_keyword(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from shared.logger import Logger

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


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .system/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```

### Bonus: Loader Code Suggestion (for `shared/config.py`)

You can later create a simple loader like this:

```python
from pathlib import Path
import json

def load_config(script_path: Path):
    project_root = Path(__file__).resolve().parents[2]  # adjust as needed
    
    # Global
    global_path = project_root / "config" / "global.json"
    global_cfg = json.loads(global_path.read_text()) if global_path.exists() else {}
    
    # Local
    script_name = script_path.stem
    local_path = project_root / "config" / f"{script_name}.json"
    local_cfg = json.loads(local_path.read_text()) if local_path.exists() else {}
    
    # Merge (local overrides global)
    config = {**global_cfg, **local_cfg}
    return config
```

