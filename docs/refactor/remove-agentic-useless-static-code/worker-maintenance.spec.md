# Worker: maintenance

Status: SPEC · Kind: **scheduled + signal-triggered** · Replaces: `repair-agent`
Current code: `nexus/tasks/repair_agent.py`

Migrates **last** (Phase 2 order): it repairs the others, and half its
current job description dissolves when the static agents it babysits stop
existing.

## Role after the refactor

Self-healing for the pipeline that remains:

| Action | Fate |
|--------|------|
| ParseErrorPatterns (scan automation.log 24h) | keep |
| RemoveStaleLock (runner.lock > 30 min) | keep |
| CreateMissingDirs (`REQUIRED_DIRS`) | keep - list shrinks to runtime state, worker state dirs, LLM agent state |
| ValidateImageRefs (processed-images.json SHA256) | keep |
| ValidateInboxQueue (prune entries whose file is gone) | keep + extend: reset `error` slots whose `reruns < 3` when the underlying cause (missing file, missing dep) is resolved |
| DetectOverdueAgents | keep, generalized: LLM agents by agent.json interval, workers by registry `interval_seconds` (reads `worker:<name>` lastRun keys) |
| Dashboard health probe | keep |
| WriteRepairReport | keep → `system/state/workers/maintenance/reports/` |
| GenerateMissingAgentConfigs (`_AGENT_JSON_SPECS`) | **shrinks to LLM agents only** - static entries die with their agent.json |
| EnsureAgentRelationLinks (junction table) | **shrinks to LLM agents only** - static rows dropped |
| Agent scaffold (prompts/state dirs) | **LLM agents only** |

New responsibility (from contract §Errors): **poison-pill report** - list
queue slots stuck at `error` with `reruns >= 3` in the repair report so
humans see them on the dashboard.

## Worker mapping

```python
name = "maintenance"; kind = "scheduled"

def pending() -> list[WorkItem]:
    return [WorkItem("", {})]

def handle(item) -> WorkResult:
    # ordered action list above; each action isolated try/except,
    # failures counted, run always completes (current _run_step pattern).
    ...
```

Signal trigger: the runner already consumes `state/signals/`; a
`worker-error` signal emitted by the worker loop (contract §Runner loop, on
any `error` result) marks maintenance due on the next cycle regardless of
interval - replaces "repair always runs" with "repair runs daily or when
something actually failed".

## State

| Now | Target |
|-----|--------|
| `agents/repair/state/` | `system/state/workers/maintenance/` |
| report → `agents/review/state/reports/repair-*.json` | `system/state/workers/maintenance/reports/` - dashboard repair endpoint re-pointed in same commit |

## Config

```yaml
workers:
  maintenance:
    kind: scheduled
    interval_seconds: 86400        # daily; signals force earlier runs
    commit_scope: []
```

## Errors / retries

Every action already runs isolated (`_run_step`); a failing action logs and
increments `failed`, run returns `done` with counts. `error` result only if
the report itself cannot be written.

## Deletions when migrated

- `agents/repair/` (agent.json, AGENT.md, CLAUDE.md, prompts/, state/).
- `_AGENT_JSON_SPECS` static rows; `_AGENT_RELATIONS` static rows;
  scaffold loop's static coverage.
- `nexus/tasks/repair_agent.py` → `nexus/workers/maintenance.py`.
- `.claude/agents/repair.md` subagent def re-pointed to
  `python -m nexus.runner --task worker:maintenance --force` (or module run).
- No `_PRECONDITIONS` entry exists (always-run today).

## Migration steps

1. All other workers migrated first; their state paths (token index,
   worker logs) already updated here per their specs.
2. Move module; strip static rows from spec/relations tables; add
   poison-pill report + error-slot reset; generalize overdue detection.
3. Wire `worker-error` signal emission in the runner loop + consumption.
4. Re-point dashboard repair-report route; enable in registry; delete
   agent folder.
5. Tests: overdue detection across both agent kinds; error-slot reset
   respects reruns cap; stale-lock removal unchanged.

## Acceptance

1. Kill -9 the runner mid-cycle → next run removes stale lock, report
   notes it.
2. Worker item fails → signal emitted → maintenance runs next cycle (not
   24 h later), report lists the error slot.
3. Fresh clone: LLM agent.json files regenerated; **no** static agent.json
   or junction resurrected.
