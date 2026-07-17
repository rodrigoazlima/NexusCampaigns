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

# shared\loaders.py
"""Config loader - builds VaultConfig and RegistryConfig from project root.

config.py declares the VaultConfig structure; this module resolves it from disk.
registry.yaml (agent-registry.spec.md) is the single source of truth for
LLM endpoints, agent definitions, and execution order.

Auto-discovery: walks up from __file__ until finding a directory that
contains knowledge-base/. Explicit root overrides auto-detect.

Fallback endpoints (no registry.yaml present) match llm-integration.spec.md:
  vision/lore  → localhost:1234  (Qwen3-VL)
  classification → localhost:8080 (unspecified model)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from .config import LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths
from .models import RegistryConfig

_REGISTRY_RELATIVE = ".agents/registry.yaml"

_DEFAULT_ENDPOINTS: dict[str, LLMEndpointConfig] = {
    "vision": LLMEndpointConfig(
        url      = "http://localhost:1234/v1/chat/completions",
        model    = "qwen3-vl-4b-instruct",
        type     = "vision",
        provider = "lmstudio",
    ),
    "lore": LLMEndpointConfig(
        url      = "http://localhost:1234/v1/chat/completions",
        model    = "qwen3-vl-4b-instruct",
        type     = "vision",
        provider = "lmstudio",
    ),
    "classification": LLMEndpointConfig(
        url      = "http://localhost:8080/v1/chat/completions",
        model    = "unspecified",
        type     = "text",
        provider = "lmstudio",
    ),
}


def _find_project_root(start: Path) -> Path:
    """Walk up from start until a directory containing knowledge-base/ is found."""
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "knowledge-base").is_dir():
            return candidate
    raise FileNotFoundError(
        f"No project root found (missing knowledge-base/) searching up from {start}"
    )


def load_registry(project_root: Optional[Path] = None) -> RegistryConfig:
    """Parse .agents/registry.yaml and return a validated RegistryConfig.

    Args:
        project_root: Explicit project root. Auto-detects if None.

    Raises:
        FileNotFoundError: If registry.yaml does not exist.
        pydantic.ValidationError: If the YAML fails schema validation.
    """
    if project_root is None:
        project_root = _find_project_root(Path(__file__).resolve().parent)

    registry_path = project_root / _REGISTRY_RELATIVE
    if not registry_path.exists():
        raise FileNotFoundError(f"registry.yaml not found: {registry_path}")

    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    return RegistryConfig.model_validate(raw)


def load_vault_config(project_root: Optional[Path] = None) -> VaultConfig:
    """Build a VaultConfig for the current project.

    Reads llm_endpoints from .agents/registry.yaml when present.
    Falls back to hardcoded defaults when registry.yaml is absent.

    Args:
        project_root: Explicit project root. Auto-detects if None.
    """
    if project_root is None:
        project_root = _find_project_root(Path(__file__).resolve().parent)

    registry_path = project_root / _REGISTRY_RELATIVE
    if registry_path.exists():
        try:
            registry = load_registry(project_root)
            endpoints: dict[str, LLMEndpointConfig] = {
                alias: LLMEndpointConfig(
                    url      = ep.url,
                    model    = ep.model,
                    type     = ep.type,
                    provider = ep.provider,
                )
                for alias, ep in registry.llm_endpoints.items()
            }
        except Exception:
            endpoints = _DEFAULT_ENDPOINTS
    else:
        endpoints = _DEFAULT_ENDPOINTS

    return VaultConfig(
        vault_paths   = VaultPaths(vault_root=project_root / "knowledge-base"),
        system_paths  = SystemPaths(project_root=project_root),
        llm_endpoints = endpoints,
    )


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

