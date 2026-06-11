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

# tests\test_vault_guard.py
"""Tests for shared.vault_guard.VaultGuard."""

import pytest
from pathlib import Path

from shared.config import VaultPaths
from shared.vault_guard import VaultGuard, _is_under
from shared.interfaces import VaultWriteError


@pytest.fixture
def vault_root(tmp_path):
    kb = tmp_path / "knowledge-base"
    (kb / "00-Inbox").mkdir(parents=True)
    (kb / "01-Processing").mkdir(parents=True)
    (kb / "02-Library").mkdir(parents=True)
    return kb


@pytest.fixture
def guard(vault_root):
    return VaultGuard(VaultPaths(vault_root=vault_root))


class TestVaultGuardAssertWritable:
    def test_processing_is_allowed(self, guard, vault_root):
        target = vault_root / "01-Processing" / "npc-test.md"
        guard.assert_writable(target)  # must not raise

    def test_campaigns_is_allowed(self, guard, vault_root):
        target = vault_root / "03-Campaigns" / "session-01.md"
        guard.assert_writable(target)  # must not raise

    def test_library_raises(self, guard, vault_root):
        target = vault_root / "02-Library" / "npc-villain.md"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_library_subdirectory_raises(self, guard, vault_root):
        target = vault_root / "02-Library" / "npcs" / "villain.md"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_inbox_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "newfile.txt"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_inbox_images_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "images" / "portrait.png"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_error_message_mentions_path(self, guard, vault_root):
        target = vault_root / "02-Library" / "test.md"
        try:
            guard.assert_writable(target)
            pytest.fail("Expected VaultWriteError")
        except VaultWriteError as e:
            assert "02-Library" in str(e)


class TestVaultGuardAssertNotInboxDelete:
    def test_inbox_file_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "original.pdf"
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(target)

    def test_inbox_images_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "images" / "portrait.jpg"
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(target)

    def test_processing_is_allowed(self, guard, vault_root):
        target = vault_root / "01-Processing" / "draft.md"
        guard.assert_not_inbox_delete(target)  # must not raise

    def test_library_is_allowed(self, guard, vault_root):
        target = vault_root / "02-Library" / "entity.md"
        guard.assert_not_inbox_delete(target)  # must not raise

    def test_error_message_mentions_inbox(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "doc.txt"
        try:
            guard.assert_not_inbox_delete(target)
            pytest.fail("Expected VaultWriteError")
        except VaultWriteError as e:
            assert "00-Inbox" in str(e)


class TestIsUnderHelper:
    def test_direct_child(self, tmp_path):
        assert _is_under(tmp_path / "child.txt", tmp_path) is True

    def test_nested_child(self, tmp_path):
        assert _is_under(tmp_path / "a" / "b" / "c.txt", tmp_path) is True

    def test_sibling_not_under(self, tmp_path):
        parent = tmp_path / "parent"
        sibling = tmp_path / "sibling" / "file.txt"
        assert _is_under(sibling, parent) is False

    def test_same_path_is_under(self, tmp_path):
        assert _is_under(tmp_path, tmp_path) is True

    def test_parent_not_under_child(self, tmp_path):
        child = tmp_path / "child"
        assert _is_under(tmp_path, child) is False


class TestVaultWriteErrorIsPermissionError:
    def test_subclass(self):
        exc = VaultWriteError("test")
        assert isinstance(exc, PermissionError)


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

