# Worker: report

Status: SPEC · Kind: **scheduled** · Replaces: `review-agent` (daily_report)
Current code: `nexus/tasks/daily_report.py`

## Role

Pipeline health snapshot: aggregate automation logs, queue slot counts,
vault metadata violations (orphans, missing wikilinks, quality gates) into a
JSON report; rebuild `reports-data.js` for the dashboard; inject
`suggestedQuality` into `01-Processing` drafts where analysis warrants.

## Worker mapping

```python
name = "report"; kind = "scheduled"

def pending() -> list[WorkItem]:
    return [WorkItem("", {})]     # due-check is the runner's job

def handle(item) -> WorkResult:
    # today's main(): aggregate → write report JSON → rebuild
    # reports-data.js → optional suggestedQuality injections.
    # One run = one item; partial-failure sections degrade to warnings
    # inside the report rather than failing the run (current behavior).
    ...
```

No queue: this is a cron job. Runs whole-hog on its interval; the "always
run" precondition it has today (health monitor) is preserved by scheduling
alone.

## State

| Now | Target |
|-----|--------|
| `system/state/review/reports/` (report JSONs + reports-data.js) | unchanged - dashboard reads these paths |
| logs `system/state/review/logs/` | `system/state/workers/report/logs/` |

Report output paths deliberately do NOT move: dashboard `/api` routes and
`reports-data.js` consumers read them. Only worker-internal logs move.

## Config

```yaml
workers:
  report:
    kind: scheduled
    interval_seconds: 900          # current cadence (report every 15 min)
    commit_scope: [".knowledge-base/01-Processing"]   # suggestedQuality writes
```

## Guard rules (carried over)

- Never writes `02-Library/`.
- `01-Processing` frontmatter: `suggestedQuality` only - never `status`,
  `reviewed`, `quality`.

## Errors / retries

- A failing aggregation section (corrupt log line, unreadable draft) is
  captured inside the report under `warnings[]` - the run itself still
  returns `done` (matches today's resilience).
- `error` only when the report file itself cannot be written.

## Deletions when migrated

- `agents/review/` - jointly with worker-shortfiles (see that spec's
  ordering note); whichever migrates second deletes the folder.
- `_AGENT_JSON_SPECS["review"]` report entry.
- `nexus/tasks/daily_report.py` → `nexus/workers/report.py`.
- No `_PRECONDITIONS` entry exists (always-run) - nothing to remove there.

## Migration steps

1. Move module; `main()` body becomes `handle()`; no reshaping needed
   (scheduled workers are the trivial case).
2. Move log dir; enable in registry; joint agent-folder deletion with
   shortfiles.
3. Tests: report content tests re-point imports; add: report written even
   when one aggregation source is corrupt.

## Acceptance

1. Due cycle → report JSON + reports-data.js rebuilt, dashboard renders it
   unchanged.
2. Corrupt automation.log line → run completes, warning recorded in report.
3. Commit only when a suggestedQuality injection actually happened.
