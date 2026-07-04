# Spec — Automation System

---

## Process Model

```
OS Service Supervisor (NSSM / systemd / launchd)
  └─ runner.py                   # persistent loop — sole static process
       └─ every 60s: foreach task in agent.json
            if (now - lastRun) >= intervalSeconds OR signal pending:
                load agents/{name}/agent.json
                get_runner(dispatch.type)
                runner.run(dispatch_config)
                update tasks-state.json
                update agent-metrics.json
                git commit (scoped to commit_scope) if changes exist
```

**Lock file:** `agents/runtime/state/runner.lock` — prevents concurrent runner instances.
Auto-cleared after 30 minutes (stale lock recovery handled by Repair Agent).

---

## Task Configuration

**`agent.json`** — static task registry (`agent.json` does not hold script paths;
dispatch config lives in each agent's `agent.json`):

```json
{
  "cleanupDays": 90,
  "tasks": [
    {
      "id": "string",
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

Both files live at `agents/runtime/state/`. See [state-files.spec.md](state-files.spec.md) for full schemas.

---

## Agent Resolution

the runtime derives the agent folder from `task.id`:

```
repair-agent              → agents/repair/agent.json
review-agent              → agents/review/agent.json
review-agent-short-files  → agents/review/agent.json
ingestion-agent           → agents/ingestion/agent.json
```

Rule: strip the trailing `-agent[-*]` suffix; the remainder is the agent folder name.

If `agent.json` is missing the task is skipped and `lastRun` is not updated.
See [agent-dispatch.spec.md](agent-dispatch.spec.md) for the full `agent.json` schema.

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

1. Create `agents/{name}/` with subdirs: `prompts/`, `tools/`, `generated-tools/`, `state/`, `state/logs/`
2. Create `AGENT.md` following the schema in `agents/README.md` (purpose, inputs, outputs, responsibilities, restrictions, commit_scope).
3. Add entry to `registry.yaml` under `agents:` with `status: active`.
   See [agent-registry.spec.md](agent-registry.spec.md) for the full schema.
4. Create `agent.json` under `agents/{name}/` declaring the dispatch config.
   See [agent-dispatch.spec.md](agent-dispatch.spec.md) for the full schema.
5. Place tool scripts under `tools/`. For `claude-api` tool-use dispatch, define a `tools_module` pointing to the Python module.
6. The implementation must:
   - Emit `--- START ---` and `--- DONE (key: N, elapsed: Ns) ---` log lines via `shared.logger`
   - Use `shared.vault_guard.assert_writable()` before any vault write
   - Never write to `02-Library/` or set `reviewed: true`
7. Add entry to `agents/runtime/state/tasks-state.json`:
   ```json
   { "agent-id": { "lastRun": "1970-01-01T00:00:00.0000000-00:00" } }
   ```
8. Add `agent-id` to `execution_order` in `registry.yaml` at the appropriate position.
