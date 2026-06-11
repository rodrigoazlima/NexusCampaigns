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

# tests\test_defaults.py
"""Tests for shared.defaults — default state structures."""

from shared.defaults import (
    GENERATED_TOKENS_DEFAULT,
    INBOX_QUEUE_DEFAULT,
    PROCESSED_IMAGES_DEFAULT,
    PROCESSED_NPCS_DEFAULT,
    REQUIRED_DIRS,
    SCENARIOS_DEFAULT,
    STATE_FILE_DEFAULTS,
    TASKS_STATE_DEFAULT,
    TOKEN_LINKS_DEFAULT,
)


class TestDefaults:
    def test_inbox_queue_empty_dict(self):
        assert INBOX_QUEUE_DEFAULT == {}

    def test_processed_images_v2(self):
        assert PROCESSED_IMAGES_DEFAULT["version"] == 2
        assert "images" in PROCESSED_IMAGES_DEFAULT
        assert "pathIndex" in PROCESSED_IMAGES_DEFAULT

    def test_processed_npcs_empty(self):
        assert PROCESSED_NPCS_DEFAULT == {}

    def test_token_links_empty(self):
        assert TOKEN_LINKS_DEFAULT == {}

    def test_generated_tokens_empty(self):
        assert GENERATED_TOKENS_DEFAULT == {}

    def test_scenarios_has_placeholder(self):
        assert len(SCENARIOS_DEFAULT) >= 1
        assert SCENARIOS_DEFAULT[0]["active"] is False

    def test_tasks_state_has_all_agents(self):
        expected_agents = [
            "repair-agent", "review-agent", "ingestion-agent",
            "vision-agent", "lore-agent", "token-agent",
            "wiki-agent", "classification-agent",
            "review-agent-short-files", "wikilink-agent",
        ]
        for agent in expected_agents:
            assert agent in TASKS_STATE_DEFAULT, f"Missing: {agent}"
            assert TASKS_STATE_DEFAULT[agent]["lastRun"].startswith("1970")

    def test_state_file_defaults_covers_all_files(self):
        assert ".shared/state/inbox-queue.json" in STATE_FILE_DEFAULTS
        assert ".agents/vision/state/processed-images.json" in STATE_FILE_DEFAULTS
        assert ".agents/lore/state/processed-npcs.json" in STATE_FILE_DEFAULTS
        assert ".agents/runtime/state/tasks-state.json" in STATE_FILE_DEFAULTS

    def test_required_dirs_contains_shared_state(self):
        assert ".shared/state" in REQUIRED_DIRS

    def test_required_dirs_covers_all_agents(self):
        agent_names = ["ingestion", "vision", "lore", "token",
                       "classification", "wiki", "review", "repair", "wikilink"]
        for name in agent_names:
            assert any(name in d for d in REQUIRED_DIRS), f"Missing dir for: {name}"


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

