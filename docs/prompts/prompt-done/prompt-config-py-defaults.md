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

# shared\defaults.py
"""Default empty state structures for every gitignored runtime state file.

These are the values written by IStateStore.init_defaults() on first boot.
No logic — pure data. Implementations call these; they never compute them.

Keyed by canonical state file path relative to project root.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

INBOX_QUEUE_DEFAULT: dict[str, Any] = {}
"""inbox-queue.json — populated by ingestion agent."""

# ---------------------------------------------------------------------------
# Vision agent state
# ---------------------------------------------------------------------------

PROCESSED_IMAGES_DEFAULT: dict[str, Any] = {
    "version": 2,
    "images": {},
    "pathIndex": {},
}
"""processed-images.json — populated by vision agent."""

TOKEN_LINKS_DEFAULT: dict[str, Any] = {}
"""token-links.json — face-match links written by vision agent."""

# ---------------------------------------------------------------------------
# Lore agent state
# ---------------------------------------------------------------------------

PROCESSED_NPCS_DEFAULT: dict[str, Any] = {}
"""processed-npcs.json — keyed by rel_path|scenario_id composite key."""

SCENARIOS_DEFAULT: list[dict[str, Any]] = [
    # Seed with one example — users replace with real scenarios.
    {
        "id":          "default-scenario",
        "name":        "Default Scenario",
        "description": "Placeholder scenario. Replace with your campaign arcs.",
        "arc":         "A0",
        "active":      False,
    }
]
"""scenarios.json — list of active campaign scenarios consumed by lore agent."""

# ---------------------------------------------------------------------------
# Token agent state
# ---------------------------------------------------------------------------

GENERATED_TOKENS_DEFAULT: dict[str, Any] = {}
"""generated-tokens.json — keyed by source image SHA256."""

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

TASKS_STATE_DEFAULT: dict[str, Any] = {
    "repair-agent":             {"lastRun": "1970-01-01T00:00:00+00:00"},
    "review-agent":             {"lastRun": "1970-01-01T00:00:00+00:00"},
    "ingestion-agent":          {"lastRun": "1970-01-01T00:00:00+00:00"},
    "vision-agent":             {"lastRun": "1970-01-01T00:00:00+00:00"},
    "lore-agent":               {"lastRun": "1970-01-01T00:00:00+00:00"},
    "token-agent":              {"lastRun": "1970-01-01T00:00:00+00:00"},
    "wiki-agent":               {"lastRun": "1970-01-01T00:00:00+00:00"},
    "classification-agent":     {"lastRun": "1970-01-01T00:00:00+00:00"},
    "review-agent-short-files": {"lastRun": "1970-01-01T00:00:00+00:00"},
    "wikilink-agent":           {"lastRun": "1970-01-01T00:00:00+00:00"},
    "cleanup-agent":            {"lastRun": "1970-01-01T00:00:00+00:00"},
}
"""tasks-state.json — last-run timestamps, reset to epoch forces immediate first run."""

# ---------------------------------------------------------------------------
# Wikilink agent state
# ---------------------------------------------------------------------------

WIKILINK_STATE_DEFAULT: dict[str, Any] = {}
"""wikilink-state.json — keyed by relative path, tracks processed files."""

# ---------------------------------------------------------------------------
# Relationship agent state
# ---------------------------------------------------------------------------

RELATIONSHIP_GRAPH_DEFAULT: dict[str, Any] = {
    "version":     1,
    "generatedAt": "1970-01-01T00:00:00+00:00",
    "edges":       [],
}
"""relationship-graph.json — populated by relationship agent."""

# ---------------------------------------------------------------------------
# Canon agent state
# ---------------------------------------------------------------------------

CANON_REPORT_DEFAULT: dict[str, Any] = {
    "date":             "",
    "generatedAt":      "1970-01-01T00:00:00+00:00",
    "violations":       [],
    "entities_scanned": 0,
    "entities_clean":   0,
}
"""canon-report-latest.json — most recent canon integrity report."""

# ---------------------------------------------------------------------------
# Search agent state
# ---------------------------------------------------------------------------

SEARCH_INDEX_DEFAULT: dict[str, Any] = {
    "version":    1,
    "indexed_at": "1970-01-01T00:00:00+00:00",
    "entries":    {},
}
"""search-index.json — full-text entity index built by search agent."""

# ---------------------------------------------------------------------------
# Deduplication agent state
# ---------------------------------------------------------------------------

DEDUP_REPORT_DEFAULT: dict[str, Any] = {
    "date":          "",
    "generatedAt":   "1970-01-01T00:00:00+00:00",
    "candidates":    [],
    "files_scanned": 0,
}
"""dedup-report-latest.json — most recent deduplication candidates."""

# ---------------------------------------------------------------------------
# Mapping: canonical relative path → default value
# Used by implementations to resolve which default to write.
# ---------------------------------------------------------------------------

STATE_FILE_DEFAULTS: dict[str, Any] = {
    ".shared/state/inbox-queue.json":                           INBOX_QUEUE_DEFAULT,
    ".agents/vision/state/processed-images.json":               PROCESSED_IMAGES_DEFAULT,
    ".agents/vision/state/token-links.json":                    TOKEN_LINKS_DEFAULT,
    ".agents/lore/state/processed-npcs.json":                   PROCESSED_NPCS_DEFAULT,
    ".agents/lore/state/scenarios.json":                        SCENARIOS_DEFAULT,
    ".agents/token/state/generated-tokens.json":                GENERATED_TOKENS_DEFAULT,
    ".agents/runtime/state/tasks-state.json":              TASKS_STATE_DEFAULT,
    ".agents/wikilink/state/wikilink-state.json":               WIKILINK_STATE_DEFAULT,
    ".agents/relationship/state/relationship-graph.json":       RELATIONSHIP_GRAPH_DEFAULT,
    ".agents/canon/state/canon-report-latest.json":             CANON_REPORT_DEFAULT,
    ".agents/search/state/search-index.json":                   SEARCH_INDEX_DEFAULT,
    ".agents/deduplication/state/dedup-report-latest.json":     DEDUP_REPORT_DEFAULT,
}

# Directories that must exist before any agent runs
REQUIRED_DIRS: list[str] = [
    ".shared/state",
    ".agents/runtime/state",
    ".agents/runtime/state/logs",
    ".agents/ingestion/state",
    ".agents/vision/state",
    ".agents/lore/state",
    ".agents/token/state",
    ".agents/classification/state",
    ".agents/wiki/state",
    ".agents/review/state",
    ".agents/review/state/reports",
    ".agents/review/state/logs",
    ".agents/repair/state",
    ".agents/wikilink/state",
    ".agents/relationship/state",
    ".agents/canon/state",
    ".agents/canon/state/reports",
    ".agents/search/state",
    ".agents/deduplication/state",
    ".agents/deduplication/state/reports",
    ".agents/cleanup/state",
    ".agents/cleanup/state/reports",
    ".agents/curator/state",
]


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

