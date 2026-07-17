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

# shared\logger.py
"""Concrete Logger - implements ILogger.

Writes [YYYY-MM-DD HH:mm:ss] [task_id] LEVEL: message to:
  - stdout (unbuffered)
  - master automation.log  (shared across all agents)
  - per-script daily rotation log  ({script_basename}_{YYYY-MM-DD}.log)
"""

from __future__ import annotations

import io
import sys
import time
from datetime import datetime
from pathlib import Path


def _ensure_utf8_stdout() -> None:
    """Wrap stdout with UTF-8 on Windows when the default encoding is not UTF-8.

    Required by data-contracts.spec.md: stdout wrapped with
    io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace') on Windows.
    """
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8":
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )


class Logger:
    """Shared logger for all vault pipeline agents."""

    def __init__(
        self,
        task_id: str,
        script_basename: str,
        logs_dir: Path,
        master_log: Path,
    ) -> None:
        _ensure_utf8_stdout()
        self.task_id = task_id
        logs_dir.mkdir(parents=True, exist_ok=True)
        master_log.parent.mkdir(parents=True, exist_ok=True)

        stem  = script_basename.removesuffix(".py").removesuffix(".ps1")
        today = datetime.now().strftime("%Y-%m-%d")

        self._daily  = logs_dir / f"{stem}_{today}.log"
        self._master = master_log

    def _write(self, level: str, message: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{self.task_id}] {level}: {message}"
        print(line, flush=True)
        for path in (self._master, self._daily):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, message: str)    -> None: self._write("INFO",  message)
    def warning(self, message: str) -> None: self._write("WARN",  message)
    def error(self, message: str)   -> None: self._write("ERROR", message)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, *, key: str, count: int, failed: int) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write(
            "INFO",
            f"--- DONE ({key}: {count}, failed: {failed}, elapsed: {elapsed}s) ---",
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

