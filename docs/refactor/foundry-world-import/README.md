# Feature: Foundry VTT world import

Status: SPEC (idea stage - no code written)
Shared contracts referenced: [worker-contract.spec.md](../remove-agentic-useless-static-code/worker-contract.spec.md)
Specs in this feature:

| Spec | Covers |
|------|--------|
| [worker-foundry-import.spec.md](worker-foundry-import.spec.md) | `nexus.workers.foundry_import` - the queue worker that unpacks a world export and writes drafts/images into the pipeline |
| [mapping.spec.md](mapping.spec.md) | Foundry document → Nexus `EntityType`/frontmatter field mapping tables |
| [dashboard-upload.spec.md](dashboard-upload.spec.md) | dashboard upload button + API route + import-history panel |

## Problem

Game masters running a campaign in Foundry VTT already have their world's
NPCs, items, journal lore, and scene art fully written up inside Foundry. Today
the only way that content enters this vault is by hand: re-typing NPC stat
blocks and lore into `01-Processing` drafts, or re-uploading portrait/scene
images one at a time through the existing image inbox. A Foundry world export
(`.zip` of `world.json` + `data/*.db` + assets) already contains all of it in
structured form - importing it directly saves that re-entry work and skips a
classification pass the vision pipeline would otherwise have to guess at from
pixels alone.

## Target architecture

```
 dashboard "Import Foundry World"                 nexus.runner (single process)
        │ POST zip                                          │
        ▼                                                    │
 00-Inbox/foundry-worlds/<slug>-<ts>.zip   ──pending()──►  foundry-import worker
                                                              │
                                     ┌────────────────────────┼─────────────────────────┐
                                     ▼                        ▼                         ▼
                          01-Processing/*.md          00-Inbox/images/            system/state/workers/
                        (actors, world items,         foundry-import/<slug>/     foundry-import/
                         journal entries -             (portraits, item icons,   processed-worlds.json
                         direct draft, no LLM)          scene backgrounds -       (sha256 ledger, world
                                                         re-enters the normal      title, counts, status)
                                                         ingestion → vision
                                                         pipeline unchanged)
```

- One new **queue worker** (no LLM - see
  [worker-foundry-import.spec.md](worker-foundry-import.spec.md)), same shape
  as `ingestion`/`thumbnails`/`token`. It is a *producer* for the image
  pipeline (drops extracted assets into `00-Inbox/images/`, same as a human
  drag-and-drop) and a *direct writer* for text-bearing documents (actors,
  world items, journal entries), because those already carry Foundry's own
  `name`/`type`/description - re-deriving that from a vision LLM would be
  strictly lossy.
- Scene backgrounds are **not** turned into drafts by this worker - they're
  just images, so they go through `00-Inbox/images/` and get classified as
  `battlemap`/`scene` by the existing vision agent like any other map drop.
  Same for embedded actor portraits/tokens: the worker copies the file, the
  existing pipeline classifies it. Only the *structured JSON* is new ground.
- Everything this worker writes lands in `01-Processing` as `status: draft`,
  `reviewed: false`, `quality: 0` - same as every other pipeline stage. A
  human reviews and promotes, same as any other draft. This worker cannot set
  `status: approved` or `reviewed: true` (vault_guard rule, unchanged).
- No new `EntityType` values - Foundry's actor/item/journal types map onto
  the existing 18-value taxonomy (see [mapping.spec.md](mapping.spec.md)).

## What's explicitly out of scope (v1)

- **LevelDB-format worlds.** Foundry v11+ stores live world data in per-pack
  LevelDB folders (`data/actors/000003.ldb`, ...), not the older
  newline-delimited-JSON `.db` files. Parsing that needs a LevelDB reader
  dependency this repo doesn't have. v1 only parses the classic NeDB `.db`
  shape (still what compendium *exports* and many world backups use). A world
  in the unsupported shape fails one `handle()` with a clear error detail
  ("unsupported world format: LevelDB, expected NeDB .db files") instead of
  silently producing nothing - upgrade path is a `leveldb`-reading library
  swapped into the parser, same `pending()`/`handle()` shape.
- **Embedded actor inventory as separate entities.** An actor's owned items
  (`actor.items[]`, embedded in the actor doc) become a plain equipment list
  in the NPC draft body, not their own `item-*.md` files - only *unowned*
  `items.db` entries (world/loot items) get their own draft. Importing every
  goblin's dagger as a standalone artifact is churn, not value.
- **Auto-relationships.** Drafts are written with `relationships: []`. Foundry
  doesn't give a clean, reliable signal for "this journal entry is about that
  actor" - guessing wrong here is worse than leaving it for the human
  reviewer, who already adds relationships as part of promoting any draft.
- **Scene walls/lighting/grid config.** Not campaign content Nexus models;
  only the background image is worth anything to this vault.
- **Compendium packs** (`packs/*.db` - reusable content bundled with a system
  or module, not the GM's own world). Only `data/*.db` (the world's own
  actors/items/journal/scenes) is read.

## Decision log

| Decision | Choice | Why |
|----------|--------|-----|
| Direct-to-draft vs. route through vision | direct-to-draft for text docs, vision for images | Foundry already supplies name/type/description; re-deriving via image classification throws away known-good structured data |
| Worker vs. LLM agent | worker (no LLM) | transform is a deterministic JSON→frontmatter mapping, not generation - no prompt needed |
| Zip staging location | `00-Inbox/foundry-worlds/` | keeps the "00-Inbox = raw unprocessed material" rule intact; the zip itself is the raw source, same as a dropped image |
| Dedup key | zip sha256 in worker's own ledger | mirrors `processed-images.json`; re-uploading the same export is a no-op, not a duplicate-content bug |
| Actor inventory | inline list, not separate entities | avoids entity-count explosion from embedded loot; see scope-cut above |
| Relationships | left empty, human fills in | no reliable auto-link signal; matches "agents may recommend, never assert canon links speculatively" spirit |
| LevelDB worlds | unsupported v1, clear error | avoids adding a new binary-format dependency before it's known anyone needs it |

## Open questions for whoever picks this up

None blocking the spec - the one real judgment call (LevelDB vs NeDB) is
already resolved above as a documented scope cut, not a question. If a real
Foundry export turns out to already be LevelDB-only by default in the
targeted Foundry version, that scope cut becomes the v1 blocker and moves to
the top of the backlog instead of being a "later" item.
