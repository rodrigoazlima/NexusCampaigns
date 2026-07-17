# Worker: wikilink

Status: SPEC · Kind: **queue consumer** (derived pending set) · Replaces: `wikilink-agent`
Current code: `nexus/tasks/wikilink_library.py`

## Role

Cross-link approved canon: score entity pairs across `02-Library/**/*.md`
and insert `## Related` wikilink sections in-place (body only - **never
frontmatter**). The only worker allowed to write `02-Library/`.

## Worker mapping

```python
name = "wikilink"; kind = "queue"

def pending() -> list[WorkItem]:
    # today's _wikilink_has_pending: library .md files whose mtime >
    # processedAt in wikilink-state.json (corrupt state ⇒ reprocess all).
    # One item per changed file, capped by batch_size (today: 20/run).
    ...

def handle(item) -> WorkResult:
    # one library file: resolve candidate links (shared linking_rules +
    # IWikilinkResolver impl), insert/refresh ## Related, update
    # wikilink-state.json processedAt for that file.
    ...
```

Pending set is **derived** (mtime vs own state), not an inbox-queue slot -
library files aren't inbox entries. Lifecycle semantics still apply: a file
whose handle() raises is recorded in worker state as `error` with its mtime,
re-eligible after rerun reset per contract.

## Hard invariants (carried over - the vault-guard rules)

- Body-only edits. Frontmatter is read, never written, by this worker.
- No writes outside `02-Library/`.
- `status: approved` / `reviewed: true` never touched (human-only fields).
- Idempotent: re-running on an already-linked file changes nothing.

## State

| Now | Target |
|-----|--------|
| `system/state/wikilink/wikilink-state.json` | `system/state/workers/wikilink/state.json` |
| logs under `system/state/wikilink/` | `system/state/workers/wikilink/logs/` |

## Config

```yaml
workers:
  wikilink:
    kind: queue
    batch_size: 20
    interval_seconds: 3600      # min poll gap - library churn is slow
    commit_scope: [".knowledge-base/02-Library"]
```

## Errors / retries

- Unparseable frontmatter → `skip` + detail (file needs human fix; retrying
  is useless). Never blocks other files.
- State file corrupt → treat all as unprocessed (current behavior),
  WARN - self-heals by rebuilding processedAt entries.

## Deletions when migrated

- `agents/wikilink/` (agent.json, AGENT.md, CLAUDE.md, prompts/, state/).
- `runner._PRECONDITIONS["wikilink-agent"]` + `_wikilink_has_pending`.
- `_AGENT_JSON_SPECS["wikilink"]`.
- `nexus/tasks/wikilink_library.py` → `nexus/workers/wikilink.py`.

## Migration steps

1. Move module; `pending()` = mtime scan, `handle()` = per-file body of the
   batch loop; resolver + scoring helpers move verbatim.
2. Move state file (rename key layout only if free); keep schema.
3. Enable in registry; delete agent folder, precondition, spec entry.
4. Tests: `tests/test_wikilink.py` re-points imports; add invariant test:
   handle() on a file with `status: approved` leaves frontmatter
   byte-identical.

## Acceptance

1. Touch 3 library files → next cycle links them, commit stages only
   `02-Library`, state records their mtimes.
2. Untouched library → `pending()` = [] (no scan churn beyond one mtime walk).
3. File with broken frontmatter → skip logged, other 2 processed.
