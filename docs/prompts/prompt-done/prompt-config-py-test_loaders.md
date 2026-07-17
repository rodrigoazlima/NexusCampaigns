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

# tests\test_loaders.py
"""Tests for shared.loaders.load_vault_config."""

import pytest
from pathlib import Path

from shared.loaders import load_vault_config, _find_project_root
from shared.config import VaultConfig


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / "knowledge-base").mkdir()
    return tmp_path


class TestFindProjectRoot:
    def test_finds_root_from_direct_parent(self, project_root):
        found = _find_project_root(project_root)
        assert found == project_root

    def test_finds_root_from_nested_subdirectory(self, project_root):
        nested = project_root / "a" / "b" / "c"
        nested.mkdir(parents=True)
        found = _find_project_root(nested)
        assert found == project_root

    def test_raises_if_no_knowledge_base(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="knowledge-base"):
            _find_project_root(tmp_path)

    def test_finds_root_from_file_path(self, project_root):
        f = project_root / ".agents" / "shared" / "loaders.py"
        f.parent.mkdir(parents=True)
        f.touch()
        found = _find_project_root(f)
        assert found == project_root


class TestLoadVaultConfig:
    def test_explicit_root_returns_config(self, project_root):
        cfg = load_vault_config(project_root)
        assert isinstance(cfg, VaultConfig)

    def test_vault_paths_point_to_knowledge_base(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.vault_root == project_root / "knowledge-base"

    def test_inbox_path(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.inbox == project_root / "knowledge-base" / "00-Inbox"

    def test_library_path(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.library == project_root / "knowledge-base" / "02-Library"

    def test_system_paths_project_root(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.system_paths.project_root == project_root

    def test_llm_endpoints_present(self, project_root):
        cfg = load_vault_config(project_root)
        assert "vision" in cfg.llm_endpoints
        assert "lore" in cfg.llm_endpoints
        assert "classification" in cfg.llm_endpoints

    def test_vision_endpoint_port_1234(self, project_root):
        cfg = load_vault_config(project_root)
        assert "1234" in cfg.llm_endpoints["vision"].url

    def test_classification_endpoint_port_8080(self, project_root):
        cfg = load_vault_config(project_root)
        assert "8080" in cfg.llm_endpoints["classification"].url

    def test_vision_type_is_vision(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.llm_endpoints["vision"].type == "vision"

    def test_classification_type_is_text(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.llm_endpoints["classification"].type == "text"

    def test_auto_detect_from_real_project(self):
        # Auto-detect from this repo - knowledge-base/ exists
        cfg = load_vault_config()
        assert cfg.vault_paths.vault_root.name == "knowledge-base"
        assert cfg.vault_paths.vault_root.exists()

    def test_endpoints_are_frozen(self, project_root):
        cfg = load_vault_config(project_root)
        ep = cfg.llm_endpoints["vision"]
        with pytest.raises((AttributeError, TypeError)):
            ep.url = "http://other"  # type: ignore[misc]


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

