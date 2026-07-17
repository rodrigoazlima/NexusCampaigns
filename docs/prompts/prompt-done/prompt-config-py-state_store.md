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

# shared\state_store.py
"""Concrete StateStore implementations - satisfy IStateStore.

StateStore     - atomic JSON reads/writes via tmp-rename pattern.
TextStateStore - atomic newline-delimited plain-text state files (set[str]).
bootstrap_vault_state - idempotent one-call startup helper.

BOM-stripping on read covers Windows PowerShell UTF-8-BOM output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .interfaces import IStateStore


class StateStore(IStateStore):
    """Atomic JSON state file reader/writer."""

    def __init__(self, path: Path, default: Any) -> None:
        self._path    = path
        self._default = default

    def load(self) -> Any:
        if not self._path.exists():
            return (
                self._default.copy()
                if isinstance(self._default, (dict, list))
                else self._default
            )
        text = self._path.read_text(encoding="utf-8").lstrip("﻿")
        return json.loads(text)

    def save(self, data: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def update(self, updater: Callable[[Any], Any]) -> None:
        data   = self.load()
        result = updater(data)
        self.save(result if result is not None else data)

    def init_defaults(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self.save(self._default)


class TextStateStore(IStateStore):
    """Atomic state store for newline-delimited plain-text files.

    Used for processed-docx.txt, processed.txt, bad-wiki-docs.txt, bad-docs.txt.

    load()  → set[str] of non-empty stripped lines
    save()  → sorted lines with trailing newline (atomic tmp-rename)
    update() → load → apply updater(set[str]) → save
    init_defaults() → creates empty file if absent (idempotent)
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> set[str]:
        if not self._path.exists():
            return set()
        return {
            ln.strip()
            for ln in self._path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }

    def save(self, data: Any) -> None:  # data: set[str] | list[str] | iterable
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = sorted(data)
        content = "\n".join(lines) + "\n" if lines else ""
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(self._path)

    def update(self, updater: Callable[[set[str]], Any]) -> None:
        data   = self.load()
        result = updater(data)
        self.save(result if result is not None else data)

    def init_defaults(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("", encoding="utf-8")


def bootstrap_vault_state(project_root: Path) -> None:
    """Create all required state directories and initialize missing state files.

    Idempotent - never overwrites existing files. Call once on runner/agent
    startup to guarantee a consistent on-disk state before any agent runs.

    Covers:
      - All REQUIRED_DIRS (mkdir -p)
      - All JSON state files in STATE_FILE_DEFAULTS (via StateStore.init_defaults)
      - All plain-text state files in TEXT_STATE_FILES (via TextStateStore.init_defaults)
    """
    from .defaults import REQUIRED_DIRS, STATE_FILE_DEFAULTS, TEXT_STATE_FILES

    for rel in REQUIRED_DIRS:
        (project_root / rel).mkdir(parents=True, exist_ok=True)

    for rel_path, default in STATE_FILE_DEFAULTS.items():
        StateStore(project_root / rel_path, default).init_defaults()

    for rel_path in TEXT_STATE_FILES:
        TextStateStore(project_root / rel_path).init_defaults()


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

