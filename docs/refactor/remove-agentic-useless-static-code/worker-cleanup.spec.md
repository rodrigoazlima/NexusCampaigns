# Worker: cleanup

Status: SPEC · Kind: **scheduled** · Replaces: `cleanup-agent`
Current code: `nexus/tasks/cleanup_agent.py`

## Role

Housekeeping: purge log files older than `CLEANUP_DAYS` (90), purge old
report files, trim `agent-metrics.json` run history to last 100 per entry,
write a CleanupReport JSON. Lowest-risk worker — first to migrate (Phase 2
order), proving the contract end to end.

## Worker mapping

```python
name = "cleanup"; kind = "scheduled"

def pending() -> list[WorkItem]:
    return [WorkItem("", {})]

def handle(item) -> WorkResult:
    # today's main(): purge logs → purge reports → trim metrics →
    # write cleanup report. All idempotent deletes.
    ...
```

Today's `_has_old_logs(days=7)` precondition becomes an internal early-out:
`handle()` returns `skip` with detail "nothing old enough" instead of the
runner knowing cleanup's business.

## Scan roots (updated for the worker world)

Log/report purge roots become:
- `agents/runtime/state/logs/` (runner + service logs)
- `system/state/workers/*/logs/` (all worker logs)
- `agents/*/state/logs/` (remaining LLM agents)
- `system/state/review/reports/`, `system/state/workers/*/reports/`

The list lives in the worker module, not config — it tracks the state
layout, which is code's business.

## State

| Now | Target |
|-----|--------|
| `agents/cleanup/state/reports/cleanup-*.json` | `system/state/workers/cleanup/reports/` |
| logs `agents/cleanup/state/logs/` | `system/state/workers/cleanup/logs/` |

## Config

```yaml
workers:
  cleanup:
    kind: scheduled
    interval_seconds: 86400
    commit_scope: []
    options:
      retention_days: 90       # replaces hardcoded CLEANUP_DAYS
```

## Errors / retries

- Locked/undeletable file → count in `failed`, continue (current behavior).
- Metrics file corrupt → skip trim with WARN, never rewrite blind
  (current BOM-strip + parse guard carries over).

## Protected paths (carried over, verbatim)

Never deletes: state files (`inbox-queue.json`, `processed-*.json`,
`tasks-state.json`, any `*.json` outside `reports/`/`logs/` dirs), anything
under `.knowledge-base/`.

## Deletions when migrated

- `agents/cleanup/` (agent.json, AGENT.md, CLAUDE.md, prompts/, state/).
- `runner._PRECONDITIONS["cleanup-agent"]` + `_has_old_logs`.
- `_AGENT_JSON_SPECS["cleanup"]`.
- `nexus/tasks/cleanup_agent.py` → `nexus/workers/cleanup.py`.

## Migration steps

1. Move module; `main()` → `handle()`; add `retention_days` option;
   extend scan roots for `system/state/workers/`.
2. Enable in registry; delete agent folder, precondition, spec entry.
3. Tests: `tests/test_cleanup_agent.py` re-points imports (purge/trim/report
   tests unchanged — pure functions).

## Acceptance

1. Log file aged 91 days → deleted; 89 days → kept; report written.
2. Metrics entry with 150 runs → trimmed to 100, atomic write.
3. Nothing old → `skip` result, cycle logs one line, no report churn.
