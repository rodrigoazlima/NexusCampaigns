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
# Orchestrator state
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
}
"""tasks-state.json — last-run timestamps, reset to epoch forces immediate first run."""

# ---------------------------------------------------------------------------
# Mapping: canonical relative path → default value
# Used by implementations to resolve which default to write.
# ---------------------------------------------------------------------------

STATE_FILE_DEFAULTS: dict[str, Any] = {
    ".shared/state/inbox-queue.json":                      INBOX_QUEUE_DEFAULT,
    ".agents/vision/state/processed-images.json":          PROCESSED_IMAGES_DEFAULT,
    ".agents/vision/state/token-links.json":               TOKEN_LINKS_DEFAULT,
    ".agents/lore/state/processed-npcs.json":              PROCESSED_NPCS_DEFAULT,
    ".agents/lore/state/scenarios.json":                   SCENARIOS_DEFAULT,
    ".agents/token/state/generated-tokens.json":           GENERATED_TOKENS_DEFAULT,
    ".agents/orchestrator/state/tasks-state.json":         TASKS_STATE_DEFAULT,
}

# Directories that must exist before any agent runs
REQUIRED_DIRS: list[str] = [
    ".shared/state",
    ".agents/orchestrator/state",
    ".agents/orchestrator/state/logs",
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
]
