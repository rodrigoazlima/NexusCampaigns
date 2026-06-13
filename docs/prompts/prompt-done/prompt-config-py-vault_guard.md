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
   - Do not include code — only configuration.

---

**Script to analyze:**

# shared\vault_guard.py
"""Concrete VaultGuard — implements IVaultGuard.

Enforces write-protection rules from security.spec.md:
  - Agents may NOT write to 02-Library/ (human promotion only)
  - Agents may NOT delete files from 00-Inbox/ (source preservation)
  - Agents may NOT set reviewed=True or status='approved' in frontmatter (G3)

Note: Ingestion Agent renames files within 00-Inbox/ — it does NOT call
assert_writable() because renaming is an explicit responsibility defined in
its AGENT.md. VaultGuard is for agents writing new content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import VaultPaths
from .interfaces import IVaultGuard, VaultWriteError

# Frontmatter fields that only humans may set to their protected values.
_HUMAN_ONLY_FIELDS: dict[str, Any] = {
    "reviewed": True,
    "status":   "approved",
}


class VaultGuard(IVaultGuard):
    """Enforces vault security constraints on file operations."""

    def __init__(self, vault_paths: VaultPaths) -> None:
        self._library = vault_paths.library.resolve()
        self._inbox   = vault_paths.inbox.resolve()

    def assert_writable(self, target: Path) -> None:
        resolved = target.resolve()
        if _is_under(resolved, self._library):
            raise VaultWriteError(
                f"Agents may not write directly to 02-Library/: {target}"
            )
        if _is_under(resolved, self._inbox):
            raise VaultWriteError(
                f"Agents may not create new files in 00-Inbox/: {target}"
            )

    def assert_not_inbox_delete(self, target: Path) -> None:
        resolved = target.resolve()
        if _is_under(resolved, self._inbox):
            raise VaultWriteError(
                f"Agents may not delete files from 00-Inbox/: {target}"
            )

    def assert_not_self_approved(self, frontmatter: dict) -> None:
        for field, forbidden_value in _HUMAN_ONLY_FIELDS.items():
            if frontmatter.get(field) == forbidden_value:
                raise VaultWriteError(
                    f"Agents may not set {field}={forbidden_value!r} "
                    f"— human-only field (security.spec.md G3)"
                )


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


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

