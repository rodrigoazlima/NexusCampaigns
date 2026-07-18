# Dashboard: Foundry world upload

Status: SPEC
Depends on: [worker-foundry-import.spec.md](worker-foundry-import.spec.md)
Mirrors existing: `src/app/api/gm/upload-image/route.ts`,
`src/lib/upload-image.ts`, the upload button in `src/app/gm/inbox/page.tsx`

## Why a separate flow from image upload

The existing `upload-image` route/button is purpose-built for images: it
content-hashes against `processed-images.json`/the image-hash ledger and
targets `00-Inbox/images/`. A world export is a `.zip`, dedup happens
worker-side by zip hash (not at upload time - the worker already owns that
ledger, see worker spec §State), and the target folder is
`00-Inbox/foundry-worlds/`. Same shape (multipart POST → write under
`00-Inbox`), different enough contract to be its own route rather than a
branch inside `upload-image`.

## API route

New file: `src/app/api/gm/foundry-import/route.ts`

**`POST`** - multipart form, field `file` (the `.zip`).

```
1. Reject if no file, or extension isn't .zip.
2. Reject if file.size > 500 MB (dashboard-side ceiling; the worker's own
   max_extract_mb guards *uncompressed* size separately after unzip).
3. targetPath = .knowledge-base/00-Inbox/foundry-worlds/{slug(file.name)}-{Date.now()}.zip
   (timestamp suffix avoids overwriting a same-named re-upload before the
   worker has had a chance to ledger the previous one).
4. Same path-traversal guard as upload-image route (resolve, verify prefix
   is PROJECT_ROOT before writing).
5. fs.mkdirSync(recursive) + fs.writeFileSync - no hashing here (worker
   hashes on handle(), see above).
6. Return { ok: true, path: relPath }.
```

No dedup response at this layer - a duplicate upload always "succeeds" (the
file lands in the inbox); the worker's `pending()`/`handle()` is what
recognizes the content hash already exists and skips real work. This keeps
the route a thin, stateless write like `upload-image`'s.

**`GET`** - returns import history for the panel below:

```
Reads system/state/workers/foundry-import/processed-worlds.json (same file
the worker owns - dashboard only reads, never writes it, same pattern as
every other state-file-backed dashboard panel) and returns the `worlds` map
as a sorted array (newest importedAt first).
```

## Upload flow (client)

New helper: `src/lib/upload-foundry-world.ts`, same shape as
`upload-image.ts`:

```ts
export interface UploadFoundryWorldResult {
  ok: boolean
  path?: string
  error?: string
}

export function isZipFile(file: File): boolean { /* .zip extension check */ }

export async function uploadFoundryWorld(file: File): Promise<UploadFoundryWorldResult> {
  // POST multipart to /api/gm/foundry-import, same try/catch/JSON shape as uploadImage()
}
```

No `enqueueImage`-equivalent call needed after upload: unlike images (which
need an explicit `/api/gm/queue/add` to appear in `inbox-queue.json`
immediately rather than waiting for ingestion's next scan), the
foundry-import worker's own `pending()` scans `00-Inbox/foundry-worlds/`
directly every cycle - the file showing up on disk *is* the signal, same as
`ingestion`'s scan for plain dropped files.

## UI placement

Add a second action button to `/gm/inbox`'s `PageHeader.actions` (next to
the existing "Upload" image button), plus a small history panel below the
existing filter bar, visible only when there's at least one import on
record (avoids permanent empty-state clutter on vaults that never use this
feature).

```
PageHeader actions:
  [Upload]  (existing - images)
  [Import Foundry World]  (NEW - hidden file input accept=".zip", same
                            disabled-while-uploading / spinner-icon pattern
                            as the existing button)

Below filters, above the masonry grid, collapsed by default:
┌ Foundry Imports (N) ────────────────────────────────────── [collapse ▾] ┐
│ World Title       System   Imported          Actors Items Journal Images │
│ My Campaign        pf2e    2 hours ago            12    30       4    18 │
│ Old One-Shot        pf2e   3 days ago      ⚠ error: unsupported format  │
└────────────────────────────────────────────────────────────────────────┘
```

Row states: `done` → counts as plain text. `error` → red text + the ledger's
`detail` message (same red/warning styling `gm-ui-guidelines.md` uses
elsewhere, no new pattern). No per-row actions in v1 (no "retry" button -
retrying means re-exporting from Foundry and re-uploading, since a failed
import produced nothing to reprocess; see worker spec §Partial failure).

On successful upload: toast (existing `gm-ui-guidelines.md` §5 transient
toast pattern) - `"{filename} uploaded — importing on the next pipeline
cycle"` - not a synchronous "done" state, since actual processing happens
asynchronously in the runner, same honesty-about-timing the rest of this
dashboard already has for agent-driven work.

## New types

`src/lib/types.ts` addition:

```ts
export interface FoundryImportEntry {
  worldTitle: string
  foundrySystem: string
  importedAt: string
  status: 'done' | 'error'
  counts: { actors: number; items: number; journal: number; images: number; skipped: number }
  detail: string
}
```

## Out of scope (v1)

- Upload progress bar (percentage). A 500 MB zip upload has no
  server-side processing feedback to show anyway (extraction happens later,
  async, in the worker) - a spinner + toast is honest about what's actually
  known at upload time; a fake progress bar would not be.
- Drag-and-drop for world zips (`GlobalDropZone` stays image-only). World
  imports are rare, deliberate actions (one per campaign, not a batch-drop
  workflow like images) - a button is the right affordance, not a full-page
  drop target that would also have to disambiguate zips from images on every
  drop.
- Per-imported-entity links from the history panel into `/gm/review` (e.g.
  click a row → filtered list of just that import's drafts). `source: []`
  already carries `"foundry:{world title}"` on every draft this worker
  writes, so the existing review page's search/filter already reaches this
  without new code - a dedicated link is a nice-to-have, not a gap.
