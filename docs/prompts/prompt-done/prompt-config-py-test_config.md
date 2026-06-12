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

# tests\test_config.py
"""Tests for shared.config — dataclasses."""

from pathlib import Path
import pytest
from shared.config import LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths


class TestLLMEndpointConfig:
    def test_fields(self):
        cfg = LLMEndpointConfig(
            url="http://localhost:1234/v1/chat/completions",
            model="qwen3-vl",
            type="vision",
            provider="lmstudio",
        )
        assert cfg.url.startswith("http")
        assert cfg.type == "vision"

    def test_frozen(self):
        cfg = LLMEndpointConfig(url="http://x", model="m", type="text", provider="p")
        with pytest.raises((AttributeError, TypeError)):
            cfg.url = "other"  # type: ignore[misc]


class TestVaultPaths:
    def test_derived_paths(self, tmp_path):
        vp = VaultPaths(vault_root=tmp_path / "knowledge-base")
        assert vp.inbox   == tmp_path / "knowledge-base" / "00-Inbox"
        assert vp.library == tmp_path / "knowledge-base" / "02-Library"
        assert vp.processing == tmp_path / "knowledge-base" / "01-Processing"
        assert vp.campaigns  == tmp_path / "knowledge-base" / "03-Campaigns"
        assert vp.relationships == tmp_path / "knowledge-base" / "04-Relationships"
        assert vp.assets   == tmp_path / "knowledge-base" / "05-Assets"
        assert vp.archive  == tmp_path / "knowledge-base" / "99-Archive"

    def test_frozen(self, tmp_path):
        vp = VaultPaths(vault_root=tmp_path)
        with pytest.raises((AttributeError, TypeError)):
            vp.vault_root = tmp_path / "other"  # type: ignore[misc]


class TestSystemPaths:
    def test_derived_paths(self, tmp_path):
        sp = SystemPaths(project_root=tmp_path)
        assert sp.agents_dir   == tmp_path / ".agents"
        assert sp.shared_state == tmp_path / ".shared" / "state"
        assert sp.logs_dir     == tmp_path / ".agents" / "runtime" / "state" / "logs"
        assert sp.reports_dir  == tmp_path / ".agents" / "review" / "state" / "reports"

    def test_agent_state(self, tmp_path):
        sp = SystemPaths(project_root=tmp_path)
        assert sp.agent_state("vision") == tmp_path / ".agents" / "vision" / "state"

    def test_frozen(self, tmp_path):
        sp = SystemPaths(project_root=tmp_path)
        with pytest.raises((AttributeError, TypeError)):
            sp.project_root = tmp_path  # type: ignore[misc]


class TestVaultConfig:
    def test_compose(self, tmp_path):
        vp  = VaultPaths(vault_root=tmp_path / "knowledge-base")
        sp  = SystemPaths(project_root=tmp_path)
        cfg = VaultConfig(vault_paths=vp, system_paths=sp)
        assert cfg.llm_endpoints == {}

    def test_with_endpoints(self, tmp_path):
        ep = LLMEndpointConfig(url="http://x", model="m", type="text", provider="p")
        vp = VaultPaths(vault_root=tmp_path)
        sp = SystemPaths(project_root=tmp_path)
        cfg = VaultConfig(vault_paths=vp, system_paths=sp, llm_endpoints={"k": ep})
        assert "k" in cfg.llm_endpoints


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

