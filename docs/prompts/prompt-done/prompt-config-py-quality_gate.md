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

# shared\quality_gate.py
"""Quality gate implementation.

Scoring formula (+2 each, max 10):
  - description_section  : ## Description (or ## Descrição) present in body
  - has_wikilinks        : at least one [[link]] in relationships or body
  - enough_tags          : >= 3 tags in frontmatter
  - type_set             : type field present and non-empty
  - source_set           : at least one source entry

Library promotion requires: quality >= 7, reviewed=True, relationships non-empty.
"""

from __future__ import annotations

import re

from .interfaces import IQualityGate


_DESCRIPTION_HEADING = re.compile(
    r"^##\s+(description|descrição|desc)\b",
    re.IGNORECASE | re.MULTILINE,
)
_WIKILINK = re.compile(r"\[\[.+?\]\]")


class QualityGate(IQualityGate):
    """Stateless quality gate. Thread-safe."""

    def score(self, frontmatter: dict, body: str) -> int:
        points = 0

        if _DESCRIPTION_HEADING.search(body):
            points += 2

        relationships = frontmatter.get("relationships") or []
        body_links = _WIKILINK.findall(body)
        if relationships or body_links:
            points += 2

        tags = frontmatter.get("tags") or []
        if len(tags) >= 3:
            points += 2

        if frontmatter.get("type"):
            points += 2

        sources = frontmatter.get("source") or []
        if sources:
            points += 2

        return min(points, 10)

    def is_library_ready(self, frontmatter: dict) -> bool:
        quality = frontmatter.get("quality", 0)
        reviewed = frontmatter.get("reviewed", False)
        relationships = frontmatter.get("relationships") or []
        return quality >= 7 and reviewed is True and len(relationships) > 0


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

