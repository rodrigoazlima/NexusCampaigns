# Refactor: remove agentic scaffolding from static code — workers + queues

Status: SPEC (nothing implemented)
Input inventory: [agents-list.md](agents-list.md)
Shared contract: [worker-contract.spec.md](worker-contract.spec.md)

## Problem

8 of 12 scheduled tasks use no LLM, yet each one drags full agent scaffolding:
an `agents/<name>/` folder with `agent.json` (dispatch-type selection built for
LLM runners), `AGENT.md` contract, dead `prompts/system.md`, junction mounts,
per-task subprocess spawn (`python -m nexus.tasks.X` each cycle), token-cost
tracking that always records zero, and ad-hoc precondition functions hardcoded
inside `runner.py` (`_PRECONDITIONS`). The pipeline's real work-tracking
mechanism — per-entry agent slots in `system/state/inbox-queue.json` — already
behaves like a queue; the agent layer on top of it is ceremony.

## Target architecture

```
                 ┌──────────────────────────────────────────────┐
                 │ nexus.runner (single process)                │
                 │                                              │
 fs events ──►   │  producer:  ingestion worker                 │
                 │      │ registers entries                     │
                 │      ▼                                       │
                 │  inbox-queue.json  (slot: pending→done/skip) │
                 │      │ pending slots = work items            │
                 │      ▼                                       │
                 │  queue workers: thumbnails · token ·         │
                 │                 wikilink · shortfiles        │
                 │                                              │
                 │  scheduled workers (cron-like):              │
                 │      report · cleanup · maintenance          │
                 └──────────────────────────────────────────────┘
                        LLM agents (vision/lore/classification/wiki)
                        stay exactly as they are: agent.json + cli dispatch.
```

- A **worker** is a plain module in `nexus.workers.<name>` implementing the
  contract in [worker-contract.spec.md](worker-contract.spec.md): `pending()`
  (cheap poll, replaces `_PRECONDITIONS`) and `handle(item)` (one unit of
  work). No subprocess: the runner calls workers **in-process**.
- **Queue workers** consume pending slots from `inbox-queue.json` (or a
  derived pending set) one item at a time through the existing
  `locked_update_queue_entry`.
- **Scheduled workers** run on a cron-like interval from `registry.yaml` —
  they have no queue; "due" is their only trigger.
- Worker config lives in one `workers:` block in `agents/registry.yaml` —
  no per-worker JSON files, nothing machine-local to regenerate.
- Worker state moves to `system/state/workers/<name>/` — deleting the last
  reason for static `agents/<name>/` folders to exist.

## Workers (one spec each)

| Worker | Kind | Replaces task | Spec |
|--------|------|---------------|------|
| ingestion | queue producer | `ingestion-agent` | [worker-ingestion.spec.md](worker-ingestion.spec.md) |
| thumbnails | queue consumer | `thumbnails-agent` | [worker-thumbnails.spec.md](worker-thumbnails.spec.md) |
| token | queue consumer | `token-agent` | [worker-token.spec.md](worker-token.spec.md) |
| wikilink | queue consumer | `wikilink-agent` | [worker-wikilink.spec.md](worker-wikilink.spec.md) |
| shortfiles | queue consumer | `review-agent-short-files` | [worker-shortfiles.spec.md](worker-shortfiles.spec.md) |
| report | scheduled | `review-agent` | [worker-report.spec.md](worker-report.spec.md) |
| cleanup | scheduled | `cleanup-agent` | [worker-cleanup.spec.md](worker-cleanup.spec.md) |
| maintenance | scheduled + signal | `repair-agent` | [worker-maintenance.spec.md](worker-maintenance.spec.md) |

`nexus.tasks.remove_background` is a manual CLI utility — not a worker, not
scheduled; it stays as-is and is out of scope.

## Migration phases

**Phase 1 — contract + loop (no behavior change)**
1. Add `nexus/workers/` package: `base.py` (contract, `WorkItem`, `Result`),
   `registryloader` for the `workers:` block.
2. Add worker loop to `nexus.runner`: after LLM-agent dispatch, iterate
   registered workers — scheduled ones by due-time, queue ones by
   `pending()`. Feature-flag: `workers_enabled: false` in registry.yaml.

**Phase 2 — migrate workers lowest-risk first**
Order: cleanup → report → shortfiles → thumbnails → token → wikilink →
ingestion → maintenance (last: it repairs the others).
Per worker: move logic from `nexus/tasks/<mod>.py` into
`nexus/workers/<name>.py` reshaped to `pending()`/`handle()`, move state dir,
flip its registry entry on, delete its `agents/<name>/` folder and
`_PRECONDITIONS` entry. Each migration is one commit, individually
revertable.

**Phase 3 — delete the dead layer**
- `runner.py`: `_PRECONDITIONS` + `_build_preconditions`, cli-dispatch path
  for removed tasks, cost tracking for workers.
- `repair_agent.py` (now maintenance worker): `_AGENT_JSON_SPECS` static
  entries, static-agent junction relations, agent.json scaffolding for
  static agents.
- `agents/` folders: cleanup, ingestion, repair, review, thumbnails, token,
  wikilink (manifests, prompts, junction mounts). `agents/runtime/state/`
  stays (scheduler state home) until Phase 4 relocates it.
- `nexus/tasks/` modules that moved (keep `remove_background`).

**Phase 4 — docs + dashboard**
- CLAUDE.md architecture + commands, agents-list regeneration.
- Dashboard: agent cards for static tasks become worker cards (same
  metrics file, `kind: worker` field — see contract spec §Metrics).

## What survives unchanged

- LLM agents and their `agent.json`/`AGENT.md`/prompts/dispatch.
- `inbox-queue.json` shape (slot lifecycle gains one value: `error`).
- `locked_update_queue_entry`, `FileLock`, `SignalEmitter/Consumer`,
  `Logger`, vault guard.
- Auto-commit flow — commit scopes move from AGENT.md into the worker's
  registry entry (only ingestion, token, wikilink, shortfiles commit).
- `agents/runtime/state/` metrics/log locations (dashboard compatibility).

## Decision log

| Decision | Choice | Why |
|----------|--------|-----|
| In-process vs subprocess | in-process | 8 interpreter spawns/cycle for no isolation benefit; per-item try/except contains failures |
| Queue store | keep `inbox-queue.json` | already the source of truth; a broker (Redis etc.) is unjustified for a single-host, single-process pipeline |
| Config | `registry.yaml` `workers:` block | one file, already parsed, git-tracked — kills gitignored per-agent agent.json regeneration |
| Worker state location | `system/state/workers/<name>/` | removes last dependency on `agents/<name>/` dirs |
| Scheduled tasks as "queues" | no — plain due-time | forcing cron jobs through a queue is ceremony in the other direction |
| remove_background | manual utility | no trigger, no schedule — YAGNI |
