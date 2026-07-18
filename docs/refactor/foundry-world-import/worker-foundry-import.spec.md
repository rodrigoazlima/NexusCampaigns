# Worker: foundry-import

Status: SPEC · Kind: **queue consumer + producer** (writes drafts directly,
also feeds the image pipeline)
Contract: [worker-contract.spec.md](../remove-agentic-useless-static-code/worker-contract.spec.md)
Field mapping: [mapping.spec.md](mapping.spec.md)
New module: `nexus/workers/foundry_import.py`

## Role

Turns a Foundry VTT world export dropped into
`00-Inbox/foundry-worlds/*.zip` into:

1. `01-Processing/*.md` drafts for actors, world items, and journal entries
   (direct write - no LLM, no vision pass).
2. Copied image files into `00-Inbox/images/foundry-import/<world-slug>/`
   for actor portraits/tokens, item icons, and scene backgrounds, so the
   existing ingestion → vision pipeline classifies/describes them exactly
   like a manual drag-and-drop.

One `.zip` = one unit of work for `pending()`/`handle()` purposes; internally
`handle()` fans out to many files, all-or-nothing is not required (see
Partial-failure below) - a bad actor doc must not block the other 400 actors
in the same world.

## Pending / handle

```python
name = "foundry-import"; kind = "queue"

def pending() -> list[WorkItem]:
    # scan 00-Inbox/foundry-worlds/*.zip, sha256 each, compare against
    # system/state/workers/foundry-import/processed-worlds.json ledger.
    # One WorkItem per zip not already present (any status) in the ledger -
    # key = zip's sha256, payload = {"path": rel_path}.
    ...

def handle(item: WorkItem) -> WorkResult:
    # 1. Extract zip to a temp dir (stdlib zipfile; reject if uncompressed
    #    size > options.max_extract_mb, default 2048 - zip-bomb guard).
    # 2. Read world.json → {title, id, system}. Missing/unparsable → error,
    #    detail "world.json missing or invalid", ledger entry status=error.
    # 3. Detect format: data/*.db present → NeDB path (supported). Only
    #    data/<pack>/ subfolders with no top-level .db → LevelDB, unsupported
    #    → error, detail "unsupported world format: LevelDB, expected NeDB
    #    .db files" (see README §out of scope). Ledger entry status=error,
    #    counts all zero - does not retry automatically (poison-pill guard
    #    below still applies if someone forces a rerun).
    # 4. Parse each present data/*.db (actors, items, journal, scenes) as
    #    newline-delimited JSON. A malformed line is skipped with a WARN log
    #    line, not a whole-file abort.
    # 5. Per document, per mapping.spec.md: build EntityFrontmatter (or copy
    #    an image), write via nexus.shared.frontmatter_io / vault_guard
    #    exactly like any other pipeline writer (assert_writable() first).
    #    Slug collisions bump via existing build_entity_slug + numeric
    #    suffix convention (nexus.shared.slug_utils).
    # 6. Update processed-worlds.json ledger: status=done (or partial - see
    #    below), counts {actors, items, journal, images}, importedAt.
    ...
```

`pending()` stays cheap - it never opens the zip, only stats/hashes it.
Extraction, parsing, and writing all happen inside `handle()`.

## Partial failure inside one zip

A single zip commonly contains hundreds of documents; one malformed actor
doc must not sink the whole import. `handle()` tracks its own per-document
try/except internally and returns a single `WorkResult` for the zip as a
whole:

- `status: "done"` - every document that could be parsed was written.
  Per-document failures are logged (worker log, not the master log) and
  counted in the ledger's `skipped` field; the result `detail` names the
  count (`"12 actors, 40 items, 6 journal entries, 31 images (2 skipped)"`).
- `status: "error"` - only for whole-zip failures (bad zip file, missing
  `world.json`, unsupported format) where nothing was written.
- There is no partial-retry granularity below "the whole zip" - a
  document-level failure is a data problem in the export, not a transient
  fault, so it is not eligible for the poison-pill rerun path. Re-running the
  same zip (e.g. after fixing the source world in Foundry and re-exporting)
  is a **new** zip with a new sha256, which is just a new ledger entry - not
  a rerun of the old one.

## State

`system/state/workers/foundry-import/processed-worlds.json`, same v2-style
shape as `processed-images.json`:

```json
{
  "version": 1,
  "worlds": {
    "{zip sha256}": {
      "path": "00-Inbox/foundry-worlds/my-campaign-20260718.zip",
      "worldTitle": "My Campaign",
      "foundrySystem": "pf2e",
      "importedAt": "ISO-8601",
      "status": "done | error",
      "counts": { "actors": 0, "items": 0, "journal": 0, "images": 0, "skipped": 0 },
      "detail": "human-readable summary or error message"
    }
  }
}
```

Keyed by zip content hash (not filename) so re-uploading byte-identical
export is a no-op - `pending()` skips anything already keyed, regardless of
status, matching the "no automatic retry of data problems" rule above.

## Config

```yaml
workers:
  foundry-import:
    kind: queue
    batch_size: 1                 # one world at a time - extraction is I/O-heavy
    commit_scope:
      - ".knowledge-base/01-Processing"
      - ".knowledge-base/00-Inbox"
    options:
      max_extract_mb: 2048        # zip-bomb guard
      image_subdir: "foundry-import"   # under 00-Inbox/images/<subdir>/<world-slug>/
```

Defaults per contract otherwise (`enabled: true`).

## Errors / retries

| Failure | Result |
|---------|--------|
| Corrupt/non-zip file | `error`, detail "not a valid zip archive" |
| `world.json` missing/invalid | `error`, detail names it |
| LevelDB-format world | `error`, detail names unsupported format (README scope cut) |
| Extract size over `max_extract_mb` | `error`, detail "extract exceeds max_extract_mb" - refuses to unzip |
| Malformed line in a `.db` file | that document skipped, WARN logged, `skipped` count incremented, zip still `done` |
| Image file referenced but missing from zip | that image skipped, `skipped` count incremented |
| `assert_writable()` raises (vault_guard) | that document skipped (same as malformed-line handling) - never crashes the whole `handle()` |

Poison-pill guard (3 reruns) applies only to true transient failures (e.g. a
disk-full write error mid-extract) - not to the data-shape errors above,
which are correctly terminal until the source export changes (new sha256).

## Deletions when migrated

N/A - net-new worker, nothing to remove.

## Migration steps

1. Add `nexus/workers/foundry_import.py` (module shape per contract) +
   `nexus/shared/foundry_parse.py` for the pure NeDB-parsing/mapping helpers
   (importable/testable without the worker's I/O - mirrors how vision's
   `classify_image_full` is public and independently callable).
2. Add the `foundry-import` entry to `agents/registry.yaml` `workers:` block
   (declared order: after `ingestion`, so any images it drops this cycle are
   picked up by `ingestion`'s scan next cycle rather than the same one -
   no special-casing required, same as a human drag-and-drop landing between
   cycles).
3. Add dashboard upload route + button - see
   [dashboard-upload.spec.md](dashboard-upload.spec.md).
4. Unit tests (pure parser, no real install - matches
   `npm run test:unit`'s sibling on the Python side, `pytest`): one fixture
   NeDB-shaped `.db` snippet per document type, one malformed-line case, one
   LevelDB-shaped fixture asserting the unsupported-format error path.

## Acceptance

1. Drop a fixture world zip (3 actors, 2 world items, 1 journal entry with 2
   pages, 1 scene, 5 images total) into `00-Inbox/foundry-worlds/` → one
   `handle()` call produces 6 drafts in `01-Processing` (3 npc/character +
   2 item + 1 lore) and 5 images copied into
   `00-Inbox/images/foundry-import/<slug>/`, ledger entry `status: done`,
   `counts: {actors: 3, items: 2, journal: 1, images: 5, skipped: 0}`.
2. Second cycle, same zip still present: `pending()` returns `[]` (ledger
   already has that sha256).
3. Re-drop the same zip under a different filename: still a no-op (keyed by
   content hash, not path).
4. One actor doc in the fixture has an unparsable JSON line → zip still
   completes `status: done`, `skipped: 1`, other 2 actors written normally.
5. LevelDB-shaped fixture (no top-level `data/*.db`) → `status: error`,
   detail names the unsupported format, zero drafts written.
6. Every written draft has `status: draft`, `reviewed: false`, `quality: 0`,
   `relationships: []`, and passes the same structural invariants
   `assertDraftInvariants` checks in this repo's own black-box suite (UUID
   format, sha256 format where applicable, non-empty `tags`/`source`).
