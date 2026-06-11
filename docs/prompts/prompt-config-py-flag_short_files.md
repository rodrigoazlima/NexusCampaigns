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

# review\tools\flag_short_files.py
"""review.tools.15_flag_short_files

Scans 01-Processing/ for draft .md files with fewer than 10 body lines.
Logs each short file. Injects suggestedQuality: 0 into frontmatter if
quality field is 0 and suggestedQuality is absent.
No LLM. No 02-Library writes.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import FrontmatterIO  # noqa: E402

TASK_ID         = "review-agent-short-files"
SCRIPT_BASENAME = "flag_short_files.py"
MIN_BODY_LINES  = 10

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_AGENT_STATE = _AGENTS_DIR / "review" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"


class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"flag-short-files_{today}.log"
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


def _inject_suggested_quality(path: Path, fio: FrontmatterIO, log: _Logger) -> None:
    try:
        fm, body = fio.read(path)
        if fm.get("quality", 0) == 0 and "suggestedQuality" not in fm:
            fm["suggestedQuality"] = 0
            fio.write(path, fm, body)
    except Exception as exc:
        log.warning(f"Could not inject suggestedQuality in {path.name}: {exc}")


def main() -> None:
    log = _Logger()
    t0  = log.start()
    fio = FrontmatterIO()
    flagged = 0
    scanned = 0

    if not _PROCESSING.exists():
        log.info("01-Processing/ does not exist — nothing to scan")
        log.done(t0)
        sys.exit(0)

    for md_path in sorted(_PROCESSING.glob("**/*.md")):
        scanned += 1
        try:
            fm, body = fio.read(md_path)
        except Exception as exc:
            log.warning(f"Read error {md_path.name}: {exc}")
            continue

        body_lines = [ln for ln in body.splitlines() if ln.strip()]
        if len(body_lines) < MIN_BODY_LINES:
            flagged += 1
            log.warning(
                f"Short file ({len(body_lines)} body lines): {md_path.relative_to(_PROJECT_ROOT).as_posix()}"
            )
            _inject_suggested_quality(md_path, fio, log)

    log.info(f"Scanned {scanned} files — {flagged} flagged as short (< {MIN_BODY_LINES} lines)")
    log.done(t0, count=flagged)
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
        "name": "scan_short_files",
        "description": (
            "Scan 01-Processing/ for draft .md files with fewer than 10 body lines. "
            "Returns a JSON list of {path, body_lines} objects."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "flag_reprocessing",
        "description": (
            "Inject suggestedQuality: 0 into the frontmatter of a short file "
            "that has quality=0 and no existing suggestedQuality."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the .md file"},
            },
            "required": ["path"],
        },
    },
]


def _tool_scan_short_files() -> str:
    import json as _json
    fio = FrontmatterIO()
    results = []
    if not _PROCESSING.exists():
        return _json.dumps([])
    for md_path in sorted(_PROCESSING.glob("**/*.md")):
        try:
            _, body = fio.read(md_path)
            body_lines = [ln for ln in body.splitlines() if ln.strip()]
            if len(body_lines) < MIN_BODY_LINES:
                results.append({
                    "path": str(md_path),
                    "body_lines": len(body_lines),
                })
        except Exception:
            continue
    return _json.dumps(results)


def call_tool(name: str, args: dict, context: dict) -> str:
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _Logger()
    if name == "scan_short_files":
        return _tool_scan_short_files()
    if name == "flag_reprocessing":
        _inject_suggested_quality(Path(args["path"]), FrontmatterIO(), log)
        return f"Flagged: {args['path']}"

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

