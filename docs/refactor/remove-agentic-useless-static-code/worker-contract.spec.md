# Worker contract

Status: SPEC
Applies to: every worker under `nexus.workers.*`

## Module shape

One module per worker: `system/src/nexus/workers/<name>.py`.

```python
# nexus/workers/base.py
@dataclass
class WorkItem:
    key: str              # queue rel-key, file path, or "" for scheduled runs
    payload: dict         # worker-specific context (queue entry, mtime, …)

@dataclass
class WorkResult:
    status: Literal["done", "skip", "error"]
    detail: str = ""      # one-line human summary; goes to the log

class Worker(Protocol):
    name: str                                  # "thumbnails"
    kind: Literal["queue", "scheduled"]

    def pending(self) -> list[WorkItem]: ...   # cheap; no side effects
    def handle(self, item: WorkItem) -> WorkResult: ...
```

Rules:

- `pending()` must be **cheap** (file stat / single JSON read). It replaces
  `runner._PRECONDITIONS`. Empty list ⇒ runner skips the worker, logs nothing
  louder than DEBUG.
- `handle()` processes **exactly one item** and persists its own progress
  before returning (crash between items loses at most one item's work).
- Scheduled workers return exactly one `WorkItem("", {})` from `pending()`
  when due; the runner's due-check happens first, so `pending()` may just
  `return [WorkItem("", {})]`.
- No worker imports another worker. Shared logic goes to `nexus.shared`.
- No LLM client imports anywhere under `nexus.workers` — that is the
  boundary this refactor exists to enforce. CI check: grep for
  `llm_client|anthropic|openai` under `nexus/workers/` must be empty.

## Runner loop

Per cycle, after LLM-agent dispatch:

```
for worker in registry.workers (declared order):
    if not enabled: continue
    if kind == "scheduled" and not due(worker): continue
    items = worker.pending()[:batch_size]
    for item in items:
        result = worker.handle(item)        # try/except per item
        record(worker, item, result)
    if any handled: update lastRun; run commit step (see §Commits)
```

- All in-process. A worker exception marks that item `error`, logs the
  traceback, and continues with the next item — it never kills the cycle.
- `lastRun` per worker persists in `agents/runtime/state/tasks-state.json`
  under key `worker:<name>` (same file the dashboard already reads).

## Queue slot lifecycle (queue workers)

Source of truth: `system/state/inbox-queue.json`, entry field
`agents.<slot>`. All writes through `locked_update_queue_entry` — one item
per lock acquisition, never batch-buffered.

```
pending ──handle ok──► done
   │  └────not applicable────► skip
   └───handle raised/failed──► error        (new value)
error ──rerun requested──► pending          (reruns.<slot> += 1)
```

- `error` is terminal until something (maintenance worker, human, dashboard
  button) resets it to `pending` and increments `reruns.<slot>`.
- Retry policy: a worker must refuse items with `reruns.<slot> >= 3` and
  leave them `error` (poison-pill guard). The maintenance worker reports
  them; humans decide.
- Workers that track work outside the inbox queue (wikilink: mtime state;
  shortfiles: scan) define their pending-set derivation in their own spec —
  same lifecycle semantics apply to their own state files.

## Configuration

Single block in `agents/registry.yaml` (git-tracked; replaces per-agent
`agent.json` for static tasks — nothing machine-local left to regenerate):

```yaml
workers_enabled: true          # global kill switch (Phase 1 ships false)
workers:
  thumbnails:
    kind: queue
    enabled: true
    batch_size: 10             # max items per cycle
    interval_seconds: 3600     # scheduled kind only; queue kind: min poll gap
    commit_scope: []           # paths for auto-commit; [] = never commit
  report:
    kind: scheduled
    enabled: true
    interval_seconds: 86400
    commit_scope: [".knowledge-base/01-Processing"]
```

Defaults when a key is absent: `enabled: true`, `batch_size: 10`,
`interval_seconds: 900`, `commit_scope: []`.

## State layout

```
system/state/workers/<name>/          # worker-owned state (moved from agents/<name>/state)
system/state/workers/<name>/logs/     # per-worker daily log
agents/runtime/state/logs/automation.log   # shared master log (unchanged)
agents/runtime/state/tasks-state.json      # lastRun, key worker:<name>
agents/runtime/state/agent-metrics.json    # metrics (unchanged file, see below)
```

Migration: each worker's Phase-2 step copies `agents/<name>/state/*` →
`system/state/workers/<name>/` once, then the old dir is deleted with the
agent folder.

## Logging

Unchanged format, `task_id` = worker name:
`[YYYY-MM-DD HH:mm:ss] [<name>] message` with `--- START ---` /
`--- DONE (processed: N, failed: M, elapsed: S) ---` markers, written to the
worker's daily log and the master log via `nexus.shared.Logger`.

## Metrics

Same `agent-metrics.json` the dashboard reads, one entry per worker run:

```json
{ "thumbnails": { "kind": "worker", "runs": [
    { "at": "...", "processed": 3, "failed": 0, "durationMs": 412 }
] } }
```

- `kind: "worker"` lets the dashboard render worker cards without a schema
  break (absent field ⇒ legacy agent).
- **No cost entry is written** — workers never touch `state/costs/`.

## Commits

Workers with a non-empty `commit_scope` get the existing runner commit step
(stage only scoped paths, commit, serialized by the git FileLock) after a
cycle in which they handled ≥1 item with status `done`. Same G-rules as
agents: never stage outside scope, never touch `02-Library` unless the scope
says so explicitly (only wikilink's does).

## Error handling summary

| Failure | Behavior |
|---------|----------|
| `pending()` raises | log WARN, treat as empty list, continue cycle |
| `handle()` raises | item → `error`, traceback to worker log, next item |
| queue file corrupt | worker skips cycle, maintenance worker flags it |
| runner crash mid-item | slot still `pending` (or `error` if worker marked it first) — re-picked next cycle; handle() must be idempotent per item |

Idempotency requirement: `handle()` re-run on the same item must be safe
(check-before-write on outputs; all current task code already behaves this
way).

## Acceptance criteria (contract level)

1. `pytest` green with `workers_enabled: false` (Phase 1 inert).
2. With `workers_enabled: true` and all workers migrated, one runner cycle
   on a queue with N pending thumbnail slots processes ≤ batch_size of them,
   marks slots, writes metrics, and spawns **zero** subprocesses for static
   work (verify: process count during cycle).
3. `grep -rE "llm_client|anthropic|openai" system/src/nexus/workers/` → empty.
4. Fresh clone + `pip install -e .` + `python -m nexus.runner --once` runs
   all workers with no `agent.json` present for them.
