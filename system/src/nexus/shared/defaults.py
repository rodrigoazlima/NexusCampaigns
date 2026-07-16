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

IMAGE_HASHES_DEFAULT: dict[str, Any] = {}
"""image-hashes.json — content-hash ledger, populated by ingestion agent
at queue-time (see nexus.shared.image_hashes.claim_image_hash)."""

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

AGENT_METRICS_DEFAULT: dict[str, Any] = {}
"""agent-metrics.json — per-task run history keyed by task-id; populated by runner."""

TASKS_STATE_DEFAULT: dict[str, Any] = {
    "vision-agent":         {"lastRun": "1970-01-01T00:00:00+00:00"},
    "lore-agent":           {"lastRun": "1970-01-01T00:00:00+00:00"},
    "wiki-agent":           {"lastRun": "1970-01-01T00:00:00+00:00"},
    "classification-agent": {"lastRun": "1970-01-01T00:00:00+00:00"},
    # workers appear as worker:<name> keys, written by the runner's worker loop
    "worker:report":        {"lastRun": "1970-01-01T00:00:00+00:00"},
    "worker:cleanup":       {"lastRun": "1970-01-01T00:00:00+00:00"},
    "worker:maintenance":   {"lastRun": "1970-01-01T00:00:00+00:00"},
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
    "system/state/inbox-queue.json":                           INBOX_QUEUE_DEFAULT,
    "system/state/image-hashes.json":                          IMAGE_HASHES_DEFAULT,
    "agents/vision/state/processed-images.json":               PROCESSED_IMAGES_DEFAULT,
    "agents/vision/state/token-links.json":                    TOKEN_LINKS_DEFAULT,
    "agents/lore/state/processed-npcs.json":                   PROCESSED_NPCS_DEFAULT,
    "agents/lore/state/scenarios.json":                        SCENARIOS_DEFAULT,
    "system/state/workers/token/generated-tokens.json":       GENERATED_TOKENS_DEFAULT,
    "agents/runtime/state/tasks-state.json":                   TASKS_STATE_DEFAULT,
    "agents/runtime/state/agent-metrics.json":                 AGENT_METRICS_DEFAULT,
    "system/state/workers/wikilink/state.json":                WIKILINK_STATE_DEFAULT,
    "agents/relationship/state/relationship-graph.json":       RELATIONSHIP_GRAPH_DEFAULT,
    "agents/canon/state/canon-report-latest.json":             CANON_REPORT_DEFAULT,
    "agents/search/state/search-index.json":                   SEARCH_INDEX_DEFAULT,
    "agents/deduplication/state/dedup-report-latest.json":     DEDUP_REPORT_DEFAULT,
}

# ---------------------------------------------------------------------------
# Plain-text state files (newline-delimited path lists)
# Handled by TextStateStore; bootstrapped as empty files on first run.
# ---------------------------------------------------------------------------

TEXT_STATE_FILES: list[str] = [
    "system/state/workers/ingestion/processed-docx.txt",
    "agents/wiki/state/processed.txt",
    "agents/wiki/state/bad-wiki-docs.txt",
    "agents/classification/state/bad-docs.txt",
]
"""Plain-text state files bootstrapped as empty on first run."""

# Directories that must exist before any agent or worker runs.
# Static tasks are workers now — their state lives under system/state/workers/.
REQUIRED_DIRS: list[str] = [
    "system/state",
    "system/state/workers",
    "agents/runtime/state",
    "agents/runtime/state/logs",
    "agents/vision/state",
    "agents/lore/state",
    "agents/classification/state",
    "agents/wiki/state",
    "agents/relationship/state",
    "agents/canon/state",
    "agents/canon/state/reports",
    "agents/search/state",
    "agents/deduplication/state",
    "agents/deduplication/state/reports",
    "agents/curator/state",
]
