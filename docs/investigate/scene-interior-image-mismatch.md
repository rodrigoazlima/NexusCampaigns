# Investigation: wrong image shown for scene-interior-01 / -02 in dashboard

**Date**: 2026-07-16
**Items**: `bd90ad76-ae81-4ad2-a2b3-19022091e459` (scene-interior-01), `030e30d7-40ca-4730-be93-4e6edc481132` (scene-interior-02), `8f762e6c-873d-4916-95f0-637206f50c8c` (scene-interior-04)
**Reported symptom**: dashboard `/gm/view/<uuid>` pages appear to show the same duplicate image across multiple notes.

## Answer: images are NOT duplicated. Hashes are NOT equal.

`sha256` on disk for all 5 `scene-interior*` inbox images:

| File | sha256 | Content |
|---|---|---|
| `scene-interior.jpg` | `9ceaf9277a9f...` | bow |
| `scene-interior.webp` | `dfbeebe55a84...` | black-blade sword, white geometric pattern |
| `scene-interior-01.jpg` | `7472cb4d4e37...` | axe, white blade |
| `scene-interior-01.webp` | `7b4ad518f479...` | LOTR gold-handle axe |
| `scene-interior-02.webp` | `91ce4f0a6080...` | trident-blade sword, flame/bubbles |

All distinct. The three investigated notes' own frontmatter `sha256:` fields (`05617ca9…`, `11d1a140…`, `22a79c4d…`) are also all distinct from each other. No de-duplication is needed — these are five genuinely different uploaded images, correctly identified as distinct by the vision agent's tags:

- `scene-interior-01.md` (bd90ad76) → tags "black blade, white patterns, rectangular guard, central button" → **matches** its own `source: scene-interior.webp` file content.
- `scene-interior-02.md` (030e30d7) → tags "axe... golden handle... the lord of the rings" → **matches** its own `source: scene-interior-01.webp` file content.
- `scene-interior-04.md` (8f762e6c) → tags "trident blade, flame tendrils, bubbles" → **matches** its own `source: scene-interior-02.webp` file content.

Frontmatter/tags are internally consistent and correct. The bug is elsewhere.

## The real bug: dashboard displays a stale cached image for 2 of the 3 notes

Visiting `http://localhost:48080/gm/view/bd90ad76-ae81-4ad2-a2b3-19022091e459` and `.../030e30d7-40ca-4730-be93-4e6edc481132` both **visually render the trident/flame sword image** (the content of `scene-interior-02.webp`), even though:

- Their frontmatter `source:` fields point to different files (`scene-interior.webp` and `scene-interior-01.webp` respectively).
- The rendered `<img src>` in the DOM is the **correct** URL for each note (verified via `document.querySelectorAll('img')`).
- `curl`-ing the `/api/image` endpoint directly (no browser involved) for both paths returns the **correct** bytes, matching the correct on-disk file exactly (`sha256` verified).
- A hard reload (`Ctrl+Shift+R`) did **not** fix the visual — still shows the trident image.

Proof, run in-page via `fetch`:

```js
// on /gm/view/030e30d7-... (scene-interior-02, source = scene-interior-01.webp, LOTR axe)
fetch(url).then(r=>r.arrayBuffer())              // default (cache used)
  → sha256 91ce4f0a6080...   // = scene-interior-02.webp (WRONG — trident image)
fetch(url, {cache:'no-store'}).then(r=>r.arrayBuffer())  // bypass cache
  → sha256 7b4ad518f479...   // = scene-interior-01.webp (CORRECT — LOTR axe)
```

The **only** difference between the two fetches of the identical URL is whether the browser's HTTP cache is consulted. This proves the server is correct and the browser is serving a stale cached response body under a URL that used to point at different bytes.

Note `scene-interior-04` (8f762e6c) happens to display correctly — but only because its real source file (`scene-interior-02.webp`) *is* the trident image, so the stale-cache coincidence doesn't show up there.

## Root cause

`system/dashboard/src/app/api/image/route.ts:66-69`:

```ts
// 00-Inbox is read-only by vault rules, so originals there never change;
// generated tokens (*-token.png) can be regenerated in place — keep those fresh.
const inInbox = normalized.replace(/\\/g, '/').includes('/00-Inbox/')
const cacheControl = inInbox && !isTokenPath(normalized) ? IMMUTABLE : 'no-cache'
```

`IMMUTABLE = 'public, max-age=31536000, immutable'` — this assumes any path under `00-Inbox/` is content-stable forever once served. That assumption is false for the *generated* filenames the vision agent writes there.

`agents/vision/tools/classify_images.py:389-400`:

```py
def _resolve_image_target(src: Path, img_slug: str) -> Path:
    """Resolve target path for in-place image rename. Bumps filename on collision."""
    ext    = src.suffix.lower()
    target = src.parent / f"{img_slug}{ext}"
    if not target.exists() or target == src:
        return target
    counter = 1
    while True:
        target = src.parent / f"{img_slug}-{counter:02d}{ext}"
        if not target.exists():
            return target
        counter += 1
```

Image filenames are derived from `{type}-{environment}` (`_image_filename_slug`, line 347) — content-generic, not content-unique. Every "scene, interior" screenshot collides on the same base slug `scene-interior`, and this function **renames the uploaded file in place** (`src.rename(target)`, line 426) to the next free `-NN` suffix it finds *at that moment* in `00-Inbox/images/`.

Separately, `_resolve_entity_path` (line 403-414) does the **same** bump-on-collision, independently, against `.md` files already in `01-Processing/`:

```py
def _resolve_entity_path(slug: str) -> Path:
    candidate = _PROCESSING / f"{slug}.md"
    ...
    counter = 1
    while True:
        candidate = _PROCESSING / f"{slug}-{counter:02d}.md"
        ...
        counter += 1
```

These two counters are **not the same counter** — one counts existing image files, the other counts existing markdown notes. They only stay in lockstep if every image ever placed into `00-Inbox/images/` under this slug still exists there unchanged when the next collision is resolved. In a long-lived vault (this is `C:\vault`, not an ephemeral test vault — ingested over multiple manual runs/sessions), that invariant doesn't hold: images may already occupy `scene-interior.webp` from a much earlier run, so a new note ends up as `scene-interior-01.md` while its image lands on the *unsuffixed* `scene-interior.webp` — one slot "ahead" of what the note-slug counter suggests.

Combined with the immutable cache header, the sequence that produced the visible bug was:

1. An earlier run's image got renamed in place to `scene-interior-01.webp` (some sword/axe content).
2. A browser session viewed a note pointing at that path; Chrome cached the response body forever (`immutable`, 1-year `max-age`).
3. A later run's vision agent classified a *different* upload (the trident sword), collided on the same generic slug, and **overwrote `scene-interior-01.webp` in place** with the new trident image (this is a rename of a *new* source file onto a path that already existed from the earlier run only if that earlier file had since been cleared — regardless of the exact prior occupant, the key fact is the path is reused across independent uploads over time).
4. Any browser that had cached the old response for that URL keeps showing the old image forever, regardless of reloads, because `immutable` tells the browser never to revalidate.

## Fix applied

`system/dashboard/src/app/api/image/route.ts` no longer trusts `00-Inbox/` paths as permanent identities. Replaced the blind `Cache-Control: immutable, max-age=1yr` with a content-hash `ETag` + `Cache-Control: no-cache` (browser always revalidates; unchanged files still get cheap 304s). Applied to both the original-image branch and the pre-generated-thumbnail branch (the thumb cache key was `sha1(path)`, not content — same bug). Verified live: hard-refreshing the poisoned cache entry now serves the correct image.

The image-filename-counter vs entity-slug-counter drift (`_resolve_image_target` vs `_resolve_entity_path` in `classify_images.py`) was left alone — it produces confusing filename numbering but, per the frontmatter check above, does not actually mis-pair a note with the wrong image's tags. Not touched.

## Update: these are not real vault uploads — they're leaked test fixtures

Cross-checking file hashes against `nexus-testing`'s own `tests/fixtures/test-images/` turned up an exact byte match for every one of the three investigated images:

| Vault file | sha256 | Test fixture |
|---|---|---|
| `00-Inbox/images/scene-interior.webp` | `dfbeebe55a84…` | `tests/fixtures/test-images/sword-buster.webp` |
| `00-Inbox/images/scene-interior-01.webp` | `7b4ad518f479…` | `tests/fixtures/test-images/axe2.webp` |
| `00-Inbox/images/scene-interior-02.webp` | `91ce4f0a6080…` | `tests/fixtures/test-images/Power_Sword.webp` |

`Power_Sword.webp` is uploaded by `tests/pipeline/stage-inbox-exclusion.spec.ts:53` (`copyFixtureWithRandomName('Power_Sword.webp')`). It is a **single fixture, uploaded once per test run** — not independent real-world content. The "duplication" question in the original write-up was answered correctly (no byte-identical duplicate *files* exist on disk right now) but the framing was wrong: this vault's `scene-interior*` cluster isn't organic multi-session campaign uploads, it's automated-test debris.

**The scope is much larger than 3 items.** `nexus-testing/.env` sets `VAULT_PATH=./.testing/vault` (the disposable, per-run vault this repo's suite is *supposed* to target) — but `tests/tmp/uploaded-fixtures.jsonl` and `tests/tmp/created-paths.jsonl` show many historical runs were invoked with `VAULT_PATH` overridden to `C:\vault` (the real campaign vault, same as this session's). Scanning `C:\vault\00-Inbox\images` for byte-matches against every file in `tests/fixtures/test-images/` found **29 exact-hash matches** (dragons, elves, orcs, barbarians, scene battlemaps, tokens — the whole fixture set), each with a corresponding draft in `01-Processing/` (83 processing notes total, the large majority named after generic vision slugs like `token-human-*.md`, `body-*.md`, `scene-*.md` rather than campaign-specific names).

`created-paths.jsonl` (the centralized cleanup ledger `tests/helpers/vault-utils.ts` is supposed to drain via `stage-inbox-exclusion.spec.ts`) already lists these exact `C:\vault\...` paths as test-created and safe to delete — the drain step just never ran against them (most invocations target the default `.testing/vault`; runs pointed at `C:\vault` apparently didn't complete/include the exclusion spec, or its drain silently failed). This explains the underlying "how was it duplicated" question fully: it's not duplication, it's **repeated test runs against the wrong (real) vault, with cleanup never catching up**.

Not acted on — deleting vault content is destructive/hard to reverse and this vault is OneDrive-backed (folder-level operations risk Cloud-Files placeholder corruption per `AGENTS.md`). Flagged for the user to decide: run the existing safe cleanup path (`drainCreatedPathsRegistry`) against `C:\vault`, or handle manually. User declined cleanup ("you will clean current codebase — do not clean anything") — `C:\vault` left untouched throughout this investigation.

## Second bug found while tracing this: the note uuid and the state-ledger uuid disagree

Digging into why this was so hard to trace turned up an independent bug, not just the caching one above. `agents/vision/tools/classify_images.py`:

- `_write_draft()` (the function that writes the note's frontmatter, including the `uuid:` field used in dashboard URLs like `/gm/view/<uuid>`) minted its own `uuid.uuid4()` — line 745, pre-fix.
- Separately, `agents/vision/state/processed-images.json`'s per-sha256 entry also carried a `"uuid"` field, generated independently at line 1159, pre-fix — `state.get("images", {}).get(sha, {}).get("uuid") or str(_uuid.uuid4())`.

These were two different random uuids for the same image/note pair, generated a few lines apart, never reconciled. `processed-images.json` is exactly the file you'd want to query "what uuid does hash X belong to?" — and its answer was wrong. This is why the earlier investigation above required manually re-hashing files and grepping the vault by hand instead of a state-file lookup.

**Fixed**: `_write_draft()` now accepts an `entity_uuid` parameter; the classify loop generates (or reuses, if already on record for that hash) the uuid *before* calling `_write_draft()`, passes it in, and reuses the same value when writing `processed-images.json`. Note frontmatter and the state ledger now agree on one identifier per image. Downstream consumers of `processed-images.json`'s `uuid` field (`nexus/workers/token.py`, `agents/lore/tools/generate_npcs.py`) automatically benefit — the uuid they read now actually matches the note.

## Third fix: no shared way to trace an image by hash/uuid through the logs

Before this, log lines across the pipeline were inconsistent: some logged a truncated hash, most logged only a filename, none logged uuid, and no two workers formatted a hash the same way. `grep <hash-or-uuid> automation.log` didn't reliably surface an image's full journey.

Added `system/src/nexus/shared/image_logging.py` — a single `image_tag(sha256=, uuid=, path=)` helper producing a consistent ` [hash=... uuid=... path=...]` log suffix (omitting empty fields), exported via `nexus.shared`. Wired into every worker/agent that touches images:

- `nexus/workers/ingestion.py` — queue registration and duplicate-detection log lines
- `agents/vision/tools/classify_images.py` — classify success, classify failure, rename-failure log lines
- `agents/vision/tools/extract_text.py` — all per-image log lines in the batch loop
- `agents/lore/tools/generate_npcs.py` — image-gone, generation-failed, and NPC-generated log lines (the last now also logs the new NPC note's own uuid — `_write_npc_draft` was changed to return it instead of silently discarding it)
- `nexus/workers/token.py` — face-match, queue-slot, token-generation-error, token-already-exists, token-created log lines
- `nexus/workers/thumbnails.py` — thumb-generation-failure log line
- `nexus/workers/maintenance.py` — `_validate_image_refs`'s pruned/mismatch/hash-error log lines (this is the existing sha256-vs-frontmatter integrity checker — it would have caught the original scene-interior mismatch had it run against `C:\vault`)

Not touched: PowerShell install/uninstall (`system/ops/*.ps1`, out of scope — not Python) and any script whose job is installing/uninstalling the service, per the request's exclusion.

Verified: every edited file re-parses, every edited worker module and standalone agent script (`classify_images.py`, `extract_text.py`, `generate_npcs.py`) imports cleanly, and the full `pytest` suite passes (one pre-existing, unrelated failure in `tests/test_wikilink.py::TestWorkerHappyPath::test_skips_already_processed` confirmed present on the unmodified branch via `git stash`).
