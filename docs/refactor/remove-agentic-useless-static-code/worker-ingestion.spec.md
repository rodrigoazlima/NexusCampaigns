# Worker: ingestion

Status: SPEC · Kind: **queue producer** · Replaces: `ingestion-agent`
Current code: `nexus/tasks/ingestion_agent.py`

## Role

First pipeline stage and the only queue **producer**: turns raw files dropped
into `00-Inbox/` into inbox-queue entries the consumer workers feed on.

Behavior carried over 1:1 from the task:
1. Strip emoji from `00-Inbox/` filenames (idempotent renames).
2. Convert `.docx` vault-wide to GFM Markdown via Pandoc.
3. Absorb stray top-level vault entries into `00-Inbox/` when
   `ingestion_options.auto_absorb_stray` (registry.yaml) is true.
4. Register each new inbox file as a queue entry with per-slot defaults
   (`ingestion: done`, LLM slots `pending`, inapplicable slots `skip`).

## Worker mapping

```python
name = "ingestion"; kind = "queue"

def pending() -> list[WorkItem]:
    # today's _inbox_has_new_files(), moved out of runner.py:
    # newest mtime under 00-Inbox > lastScanAt state → one synthetic item
    # per new/renamed file (rel path as key)
    ...

def handle(item) -> WorkResult:
    # one file: strip emoji → convert if docx → register queue entry
    # via locked_update_queue_entry. Registration is the last step, so a
    # crash before it re-picks the file next cycle (idempotent).
    ...
```

`pending()` granularity change vs the task: the task ran batch-per-cycle; the
worker emits one item per file so slot updates and failures are per-file.

## State

| Now | Target |
|-----|--------|
| `agents/ingestion/state/` (scan bookkeeping) | `system/state/workers/ingestion/` |
| writes `system/state/inbox-queue.json` | unchanged |

## Config

```yaml
workers:
  ingestion:
    kind: queue
    batch_size: 25            # files per cycle; inbox dumps can be large
    commit_scope: [".knowledge-base/00-Inbox"]   # renames + docx conversions
```

## Errors / retries

- Pandoc missing → item `error`, detail names the dependency; maintenance
  worker surfaces it. Never blocks non-docx items.
- Rename collision → `skip` with detail (existing behavior).
- Poison-pill guard per contract (3 attempts) applies to conversion errors.

## Deletions when migrated

- `agents/ingestion/` (agent.json, AGENT.md, CLAUDE.md, prompts/, state/).
- `runner._PRECONDITIONS["ingestion-agent"]` + `_inbox_has_new_files` (logic
  moves into `pending()`).
- `_AGENT_JSON_SPECS["ingestion"]` in maintenance code.
- `nexus/tasks/ingestion_agent.py` (module moves to `nexus/workers/ingestion.py`).
- `BaseAgent` inheritance — worker uses the plain contract, drops the unused
  agentic lifecycle wrapper.

## Migration steps

1. Move module → `nexus/workers/ingestion.py`; reshape `main()` batch loop
   into `pending()`/`handle()`; keep helpers verbatim.
2. Move state dir; point scan bookkeeping at new path.
3. Enable in registry.yaml; delete agent folder + precondition + spec entry.
4. Update tests: `tests/test_11_ingestion_agent.py` imports
   `nexus.workers.ingestion`; add one test: crash after rename, before
   registration → file re-picked next `pending()`.

## Acceptance

1. Drop 3 files (one emoji name, one docx, one plain) in `00-Inbox/` → one
   cycle registers 3 queue entries, renames applied, docx converted,
   commit contains only `00-Inbox` paths.
2. Second cycle: `pending()` returns `[]` (no rescan churn).
3. Kill runner mid-batch → no queue corruption, unprocessed files re-picked.
