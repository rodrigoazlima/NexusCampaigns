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

# shared\entity_scanner.py
"""Entity scanner — enumerate vault entities with parsed frontmatter.

Shared by review, curator, canon, relationship, search, and deduplication agents.
All scanning is read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .interfaces import IFrontmatterIO
from .models import EntityFrontmatter


class EntityScanner:
    """Walk one or more vault directories and yield parsed entity records."""

    def __init__(self, fio: IFrontmatterIO) -> None:
        self._fio = fio

    def scan(
        self,
        *dirs: Path,
        recursive: bool = True,
    ) -> Iterator[tuple[Path, EntityFrontmatter, str]]:
        """Yield (path, frontmatter, body) for every parseable .md file.

        Files whose frontmatter cannot be validated as EntityFrontmatter are
        silently skipped — callers get only well-formed records.

        Args:
            *dirs: One or more vault directories to scan.
            recursive: If True, recurse into subdirectories (default True).
        """
        glob_pattern = "**/*.md" if recursive else "*.md"
        for vault_dir in dirs:
            if not vault_dir.is_dir():
                continue
            for md_path in sorted(vault_dir.glob(glob_pattern)):
                try:
                    fm_dict, body = self._fio.read(md_path)
                    fm = EntityFrontmatter.model_validate(fm_dict)
                    yield md_path, fm, body
                except Exception:
                    continue

    def scan_ids(self, *dirs: Path) -> dict[str, Path]:
        """Return {entity_id: path} index for all parseable entities."""
        return {fm.id: path for path, fm, _ in self.scan(*dirs)}

    def scan_slugs(self, *dirs: Path) -> dict[str, Path]:
        """Return {filename_stem: path} index for wikilink resolution."""
        return {path.stem: path for path, _, _ in self.scan(*dirs)}

    def count(self, *dirs: Path) -> int:
        """Return total parseable entity count across all dirs."""
        return sum(1 for _ in self.scan(*dirs))


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

