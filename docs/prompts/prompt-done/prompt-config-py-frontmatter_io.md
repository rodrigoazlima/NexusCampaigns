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

# shared\frontmatter_io.py
"""Concrete FrontmatterIO — implements IFrontmatterIO.

Reads and writes YAML frontmatter in Markdown files.
Uses ruamel.yaml for round-trip fidelity when available; falls back to PyYAML.

Frontmatter block format:
    ---
    key: value
    ---
    body text
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from .interfaces import IFrontmatterIO

_FENCE_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)


# ---------------------------------------------------------------------------
# YAML helpers — ruamel first, PyYAML fallback
# ---------------------------------------------------------------------------

def _load_yaml(text: str) -> dict[str, Any]:
    try:
        from ruamel.yaml import YAML  # type: ignore[import]
        y = YAML()
        y.preserve_quotes = True
        result = y.load(text)
        return dict(result) if result else {}
    except ImportError:
        import yaml
        result = yaml.safe_load(text)
        return dict(result) if result else {}


def _dump_yaml(data: dict[str, Any]) -> str:
    try:
        from ruamel.yaml import YAML  # type: ignore[import]
        y = YAML()
        y.default_flow_style = False
        y.preserve_quotes    = True
        y.width              = 4096   # prevent line-wrapping
        buf = io.StringIO()
        y.dump(data, buf)
        return buf.getvalue()
    except ImportError:
        import yaml
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)


# ---------------------------------------------------------------------------
# FrontmatterIO
# ---------------------------------------------------------------------------

class FrontmatterIO(IFrontmatterIO):
    """Read and write YAML frontmatter blocks in Markdown files."""

    def read(self, path: Path) -> tuple[dict[str, Any], str]:
        content = path.read_text(encoding="utf-8")
        m = _FENCE_RE.match(content)
        if not m:
            return {}, content
        fm   = _load_yaml(m.group(1))
        body = content[m.end():]
        return fm, body

    def write(self, path: Path, frontmatter: dict[str, Any], body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        yaml_str = _dump_yaml(frontmatter).rstrip("\n")
        content  = f"---\n{yaml_str}\n---\n{body}"
        path.write_text(content, encoding="utf-8")


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

