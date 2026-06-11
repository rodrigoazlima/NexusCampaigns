You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.shared/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.shared/config/<script_name>.json`)
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
   - Do not include code — only configuration.

---

**Script to analyze:**

# tests\test_state_store.py
"""Tests for shared.state_store.StateStore."""

import json
from pathlib import Path

import pytest

from shared.state_store import StateStore


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "state.json", default={})


@pytest.fixture
def list_store(tmp_path):
    return StateStore(tmp_path / "list.json", default=[])


class TestStateStoreLoad:
    def test_returns_default_when_missing(self, store):
        assert store.load() == {}

    def test_returns_default_copy_not_same_object(self, tmp_path):
        default = {"a": 1}
        s = StateStore(tmp_path / "s.json", default=default)
        result = s.load()
        result["b"] = 2
        # Second load must return a fresh copy — not the mutated result
        assert s.load() == {"a": 1}

    def test_list_default_returns_copy(self, list_store):
        result = list_store.load()
        result.append("x")
        assert list_store.load() == []

    def test_loads_existing_file(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text('{"key": "value"}', encoding="utf-8")
        store = StateStore(path, default={})
        assert store.load() == {"key": "value"}

    def test_strips_bom(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_bytes(b"\xef\xbb\xbf" + b'{"x": 1}')
        store = StateStore(path, default={})
        assert store.load() == {"x": 1}

    def test_non_dict_default(self, tmp_path):
        store = StateStore(tmp_path / "s.json", default=42)
        assert store.load() == 42


class TestStateStoreSave:
    def test_creates_parent_dirs(self, tmp_path):
        path  = tmp_path / "deep" / "nested" / "state.json"
        store = StateStore(path, default={})
        store.save({"ok": True})
        assert path.exists()

    def test_writes_json(self, store, tmp_path):
        store.save({"hello": "world"})
        path    = tmp_path / "state.json"
        content = json.loads(path.read_text(encoding="utf-8"))
        assert content == {"hello": "world"}

    def test_atomic_tmp_file_cleaned_up(self, store, tmp_path):
        store.save({"x": 1})
        tmp = tmp_path / "state.tmp"
        assert not tmp.exists()

    def test_overwrites_existing(self, store):
        store.save({"a": 1})
        store.save({"b": 2})
        assert store.load() == {"b": 2}

    def test_saves_list(self, list_store):
        list_store.save([1, 2, 3])
        assert list_store.load() == [1, 2, 3]

    def test_datetime_serialised_as_string(self, store, tmp_path):
        from datetime import datetime, timezone
        store.save({"ts": datetime(2026, 1, 1, tzinfo=timezone.utc)})
        raw = (tmp_path / "state.json").read_text(encoding="utf-8")
        assert "2026" in raw


class TestStateStoreUpdate:
    def test_update_mutates_and_saves(self, store):
        store.save({"count": 0})
        store.update(lambda d: {**d, "count": d["count"] + 1})
        assert store.load()["count"] == 1

    def test_update_uses_default_when_missing(self, store):
        store.update(lambda d: {**d, "new": True})
        assert store.load()["new"] is True

    def test_update_none_return_preserves_original(self, store):
        store.save({"keep": "me"})
        store.update(lambda d: None)  # returns None → save original
        assert store.load() == {"keep": "me"}

    def test_update_called_with_loaded_data(self, store):
        store.save({"items": [1, 2]})
        seen = []
        store.update(lambda d: seen.append(d) or d)
        assert seen[0] == {"items": [1, 2]}


class TestStateStoreInitDefaults:
    def test_creates_file_if_missing(self, tmp_path):
        path  = tmp_path / "new.json"
        store = StateStore(path, default={"ready": True})
        store.init_defaults()
        assert path.exists()
        assert json.loads(path.read_text())["ready"] is True

    def test_does_not_overwrite_existing(self, tmp_path):
        path  = tmp_path / "existing.json"
        path.write_text('{"original": 1}', encoding="utf-8")
        store = StateStore(path, default={"replaced": True})
        store.init_defaults()
        assert json.loads(path.read_text())["original"] == 1

    def test_creates_parent_dirs(self, tmp_path):
        path  = tmp_path / "sub" / "state.json"
        store = StateStore(path, default={})
        store.init_defaults()
        assert path.exists()


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .shared/config/
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

