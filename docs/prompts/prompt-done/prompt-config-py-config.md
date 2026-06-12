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

# shared\config.py
"""Vault configuration structure.

Dataclasses only — no loading logic, no I/O.
Loader lives in shared.loaders (implementation layer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LLMEndpointConfig:
    url:      str
    model:    str
    type:     str      # "vision" | "text"
    provider: str


@dataclass(frozen=True)
class VaultPaths:
    """Derived path accessors from a single vault_root."""
    vault_root:   Path

    @property
    def inbox(self) -> Path:
        return self.vault_root / "00-Inbox"

    @property
    def processing(self) -> Path:
        return self.vault_root / "01-Processing"

    @property
    def library(self) -> Path:
        return self.vault_root / "02-Library"

    @property
    def campaigns(self) -> Path:
        return self.vault_root / "03-Campaigns"

    @property
    def relationships(self) -> Path:
        return self.vault_root / "04-Relationships"

    @property
    def assets(self) -> Path:
        return self.vault_root / "05-Assets"

    @property
    def archive(self) -> Path:
        return self.vault_root / "99-Archive"


@dataclass(frozen=True)
class SystemPaths:
    """Derived path accessors from a single project_root."""
    project_root: Path

    @property
    def agents_dir(self) -> Path:
        return self.project_root / ".agents"

    @property
    def shared_state(self) -> Path:
        return self.project_root / ".shared" / "state"

    @property
    def logs_dir(self) -> Path:
        return self.agents_dir / "runtime" / "state" / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.agents_dir / "review" / "state" / "reports"

    def agent_state(self, agent_name: str) -> Path:
        return self.agents_dir / agent_name / "state"


@dataclass(frozen=True)
class VaultConfig:
    vault_paths:   VaultPaths
    system_paths:  SystemPaths
    llm_endpoints: dict[str, LLMEndpointConfig] = field(default_factory=dict)


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

