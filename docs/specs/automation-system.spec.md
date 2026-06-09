# Spec — Automation System

---

## Process Model

```
NSSM Windows Service
  └─ daemon.ps1                  # persistent loop (PS 7+)
       └─ runner.ps1             # dispatched every 60s (PS 5.1+)
            └─ foreach task in tasks.json
                 if (now - lastRun) >= intervalSeconds:
                     execute script
                     update tasks-state.json
                     update agent-metrics.json
                     git commit + push if changes exist
```

**Lock file:** `.system/runner.lock` — prevents concurrent runner instances. Auto-cleared after 30 minutes (stale lock recovery handled by Repair Agent).

---

## Task Configuration

**`tasks.json`** — static task registry:

```json
{
  "cleanupDays": 90,
  "tasks": [
    {
      "id": "string",
      "script": "NN-name.ps1 | NN-name.py",
      "intervalSeconds": 900,
      "description": "string"
    }
  ]
}
```

**`tasks-state.json`** — mutable run state:

```json
{
  "task-id": {
    "lastRun": "ISO-8601 datetime"
  }
}
```

---

## Default Intervals

| Interval | Tasks |
|----------|-------|
| 900s (15 min) | `review-agent`, `repair-agent` |
| 3600s (1 h) | `ingestion-agent`, `vision-agent`, `lore-agent`, `token-agent`, `classification-agent`, `wiki-agent`, `wikilink-agent`, `review-agent-short-files` |
| 86400s (24 h) | `cleanup-agent` |

---

## Metrics

**`agent-metrics.json`** — keyed by `task-id`, last 100 runs per agent:

```json
{
  "task-id": {
    "runs": [
      {
        "startedAt": "ISO-8601",
        "finishedAt": "ISO-8601",
        "durationMs": 0,
        "itemsProcessed": 0,
        "itemsFailed": 0
      }
    ]
  }
}
```

`itemsProcessed` / `itemsFailed` parsed from the `--- DONE ---` log line via regex:  
Keywords: `classified|enriched|repairs|processed|converted|generated|linked` and `failed|failures`.

---

## Adding a New Agent

1. Create `.system/NN-{name}.ps1` or `.py` following existing conventions.
2. Script must:
   - Emit `--- START ---` and `--- DONE (key: N, elapsed: Ns) ---` log lines
   - Use shared log file + per-task log file
   - Never write to `02-Library/` without `reviewed: true`
3. Add entry to `tasks.json`:
   ```json
   { "id": "agent-id", "script": "NN-name.ps1", "intervalSeconds": 3600, "description": "..." }
   ```
4. Add entry to `tasks-state.json`:
   ```json
   { "agent-id": { "lastRun": "1970-01-01T00:00:00.0000000-00:00" } }
   ```
