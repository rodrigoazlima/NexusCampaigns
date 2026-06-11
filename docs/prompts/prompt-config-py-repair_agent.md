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

# repair\tools\repair_agent.py
"""repair.tools.12_repair_agent

Maintenance agent — no LLM, no vault content changes.
  - Removes stale runner.lock (age > 1800s)
  - Ensures all REQUIRED_DIRS exist
  - Prunes inbox-queue.json entries whose source file is gone
  - Prunes processed-images.json entries whose file is gone
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import REQUIRED_DIRS  # noqa: E402

TASK_ID         = "repair-agent"
SCRIPT_BASENAME = "repair_agent.py"

_ORCH_STATE    = _AGENTS_DIR / "runtime" / "state"
_LOCK_FILE     = _ORCH_STATE / "runner.lock"
_AGENT_STATE   = _AGENTS_DIR / "repair" / "state"
_LOGS_DIR      = _AGENT_STATE / "logs"
_MASTER_LOG    = _ORCH_STATE / "logs" / "automation.log"
_QUEUE_FILE    = _PROJECT_ROOT / ".shared" / "state" / "inbox-queue.json"
_PROC_IMAGES   = _AGENTS_DIR / "vision" / "state" / "processed-images.json"

_LOCK_STALE_S  = 1800


class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"repair-agent_{today}.log"
        self._master = _MASTER_LOG

    def _write(self, level: str, msg: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{TASK_ID}] {level}: {msg}"
        print(line, flush=True)
        self._master.parent.mkdir(parents=True, exist_ok=True)
        for p in (self._master, self._daily):
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, m: str)    -> None: self._write("INFO",  m)
    def warning(self, m: str) -> None: self._write("WARN",  m)
    def error(self, m: str)   -> None: self._write("ERROR", m)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, count: int = 0, failed: int = 0) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write("INFO", f"--- DONE --- processed={count} failed={failed} elapsed={elapsed}s")


def _repair_stale_lock(log: _Logger) -> int:
    if not _LOCK_FILE.exists():
        return 0
    try:
        data = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
        locked_at = datetime.fromisoformat(data["startedAt"])
        age = (datetime.now(timezone.utc) - locked_at).total_seconds()
        if age > _LOCK_STALE_S:
            _LOCK_FILE.unlink()
            log.info(f"Removed stale lock (age={age:.0f}s, pid={data.get('pid')})")
            return 1
    except Exception as exc:
        log.warning(f"Could not inspect lock file: {exc}")
    return 0


def _ensure_required_dirs(log: _Logger) -> int:
    created = 0
    for rel in REQUIRED_DIRS:
        d = _PROJECT_ROOT / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            log.info(f"Created missing dir: {rel}")
            created += 1
    return created


def _prune_queue(log: _Logger) -> int:
    if not _QUEUE_FILE.exists():
        return 0
    try:
        queue: dict = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error(f"Queue read error: {exc}")
        return 0

    pruned = []
    for rel_path in list(queue.keys()):
        src = _PROJECT_ROOT / rel_path
        if not src.exists():
            del queue[rel_path]
            pruned.append(rel_path)
            log.info(f"Queue prune: {rel_path}")

    if pruned:
        tmp = _QUEUE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
        tmp.replace(_QUEUE_FILE)

    return len(pruned)


def _prune_processed_images(log: _Logger) -> int:
    if not _PROC_IMAGES.exists():
        return 0
    try:
        state: dict = json.loads(_PROC_IMAGES.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error(f"processed-images read error: {exc}")
        return 0

    images = state.get("images", {})
    path_index = state.get("pathIndex", {})
    pruned = 0

    for key in list(images.keys()):
        entry = images[key]
        img_path = _PROJECT_ROOT / entry.get("path", "")
        if not img_path.exists():
            del images[key]
            pruned += 1
            log.info(f"Images prune: {entry.get('path')}")

    # Rebuild pathIndex to match surviving images
    if pruned:
        state["pathIndex"] = {
            v["path"]: k for k, v in images.items()
        }
        tmp = _PROC_IMAGES.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(_PROC_IMAGES)

    return pruned


def main() -> None:
    log = _Logger()
    t0  = log.start()
    count = 0

    count += _repair_stale_lock(log)
    count += _ensure_required_dirs(log)
    count += _prune_queue(log)
    count += _prune_processed_images(log)

    log.done(t0, count=count)
    sys.exit(0)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "remove_stale_lock",
        "description": "Remove the runner.lock file if it is older than 30 minutes. Safe to call unconditionally.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "ensure_required_dirs",
        "description": "Create any required .agents/ and .shared/ subdirectories that do not yet exist.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "prune_queue",
        "description": "Remove entries from inbox-queue.json whose source file no longer exists on disk.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "prune_processed_images",
        "description": "Remove entries from processed-images.json whose image file no longer exists. Rebuilds pathIndex.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _Logger()
    if name == "remove_stale_lock":
        n = _repair_stale_lock(log)
        return f"Removed {n} stale lock(s)"
    if name == "ensure_required_dirs":
        n = _ensure_required_dirs(log)
        return f"Created {n} missing director(ies)"
    if name == "prune_queue":
        n = _prune_queue(log)
        return f"Pruned {n} dead queue entries"
    if name == "prune_processed_images":
        n = _prune_processed_images(log)
        return f"Pruned {n} missing image entries"

    raise ValueError(f"Unknown tool: {name!r}")


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

