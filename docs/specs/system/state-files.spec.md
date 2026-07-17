# Spec - State Files

All runtime state is stored in JSON files. State files are gitignored runtime artefacts except where noted.

---

## Shared State (cross-agent)

| File | Path | Owner | Readers/Updaters |
|------|------|-------|-----------------|
| `inbox-queue.json` | `system/state/inbox-queue.json` | ingestion (creates) | vision, lore, wiki (update agent slots) |

### inbox-queue.json schema

```json
{
  "00-Inbox/images/A1/warrior.jpg": {
    "ingestedAt": "ISO-8601",
    "type": "image | document | other",
    "agents": {
      "vision":         "pending | done | skip",
      "lore":           "pending | done | skip",
      "classification": "pending | done | skip",
      "wiki":           "pending | done | skip"
    }
  }
}
```

**Agent slot assignment by file type:**

| File type | vision | lore | classification | wiki |
|-----------|--------|------|----------------|------|
| image     | pending | pending | pending | skip |
| document  | skip | skip | pending | pending |
| other     | skip | skip | skip | skip |

---

## Runtime State

| File | Path | Purpose |
|------|------|---------|
| `tasks-state.json` | `agents/runtime/state/tasks-state.json` | Last-run timestamps per task |
| `runner.lock` | `agents/runtime/state/runner.lock` | Prevents concurrent runner instances |
| `agent-metrics.json` | `agents/runtime/state/agent-metrics.json` | Per-task run history (last 100 runs) |

### tasks-state.json schema

```json
{
  "task-id": {
    "lastRun": "ISO-8601 datetime"
  }
}
```

### agent-metrics.json schema

```json
{
  "task-id": {
    "runs": [
      {
        "startedAt":      "ISO-8601",
        "finishedAt":     "ISO-8601",
        "durationMs":     0,
        "itemsProcessed": 0,
        "itemsFailed":    0
      }
    ]
  }
}
```

`itemsProcessed` / `itemsFailed` parsed from the `--- DONE ---` log line via regex.

---

## Per-Agent State

### Vision

| File | Path |
|------|------|
| `processed-images.json` | `agents/vision/state/processed-images.json` |

#### processed-images.json v2 schema

```json
{
  "version": 2,
  "images": {
    "{sha256}": {
      "path":          "relative/path/from/vault",
      "processedAt":   "ISO-8601",
      "originalName":  "string",
      "type":          "portrait | body | battlemap | scene",
      "ancestry":      "string",
      "class":         "string",
      "creature_type": "string",
      "element":       "string",
      "environment":   "string",
      "description":   "string",
      "sha256":        "string",
      "isToken":       true,
      "status":        "ok | failed | migrated"
    }
  },
  "pathIndex": {
    "relative/path": "{sha256} | path:{relative/path}"
  }
}
```

Failed images stored with pseudo-key `path:{rel}` and `status: failed`.  
Connection-error images are NOT stored - retried next run.

---

### Lore

| File | Path |
|------|------|
| `processed-npcs.json` | `agents/lore/state/processed-npcs.json` |
| `scenarios.json` | `agents/lore/state/scenarios.json` |

#### scenarios.json schema

```json
[
  {
    "id":          "string",
    "name":        "string",
    "description": "string",
    "arc":         "A0 | A1 | A2 | ...",
    "active":      true
  }
]
```

Active scenarios are used for NPC generation context. Add one entry per campaign arc.

---

### Token

| File | Path |
|------|------|
| `generated-tokens.json` | `agents/token/state/generated-tokens.json` |

#### generated-tokens.json schema

```json
{
  "{sha256}": {
    "sourcePath":   "relative/path",
    "tokenPath":    "relative/path",
    "generatedAt":  "ISO-8601"
  }
}
```

---

### Ingestion

| File | Path |
|------|------|
| `processed-docx.txt` | `agents/ingestion/state/processed-docx.txt` |

Plain text list of converted DOCX paths (one per line). Prevents re-conversion on next run.

---

### Wiki

| File | Path |
|------|------|
| `processed.txt` | `agents/wiki/state/processed.txt` |
| `bad-wiki-docs.txt` | `agents/wiki/state/bad-wiki-docs.txt` |

---

### Classification

| File | Path |
|------|------|
| `bad-docs.txt` | `agents/classification/state/bad-docs.txt` |

---

### Wikilink

| File | Path |
|------|------|
| `wikilink-state.json` | `agents/wikilink/state/wikilink-state.json` |

---

### Review

| Directory | Path |
|-----------|------|
| `reports/` | `agents/review/state/reports/` |

Report files: `report-YYYY-MM-DD.json` (daily health), `repair-YYYY-MM-DD.json` (repair runs).

---

## Logs

| File | Path | Purpose |
|------|------|---------|
| `automation.log` | `agents/runtime/state/logs/automation.log` | Consolidated all-agent log |
| Per-agent daily | `agents/{name}/state/logs/{basename}_YYYY-MM-DD.log` | Agent-scoped daily rotation |

---

## Agent Conversation History

Tool-use dispatched agents (all active `claude-api` agents) maintain conversation history files. Location: `agents/{name}/state/{name}-agent-history.json`. Used to preserve multi-turn context across scheduled runs.
