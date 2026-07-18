# Foundry → Nexus field mapping

Status: SPEC
Consumed by: [worker-foundry-import.spec.md](worker-foundry-import.spec.md)
Target frontmatter shape: `EntityFrontmatter` / `NPCFrontmatter`
(`nexus/shared/models.py`) - no new fields, no new `EntityType` values.

Source format assumed: Foundry world export, `data/*.db`, one JSON document
per line (NeDB shape - see README §out of scope for the LevelDB case).

## Common fields (every mapped document)

| `EntityFrontmatter` field | Value |
|---|---|
| `id` | `build_entity_slug(type, name)`, bumped on collision (existing `slug_utils` convention) |
| `uuid` | freshly generated (same as every other pipeline writer) |
| `status` | `draft` |
| `quality` | `0` |
| `created` / `updated` | import date (today) |
| `tags` | see per-type table below |
| `source` | `["foundry:{world.json title}"]` |
| `sha256` | sha256 of the *source document's* canonical JSON (not a file - there's no image backing a text doc) |
| `reviewed` | `false` |
| `relationships` | `[]` (README scope cut - human fills in) |
| `needs_reprocessing` | `false` |

## Actor → npc / character

Foundry pf2e `Actor.type` is already binary for exactly this distinction:

| Foundry `actor.type` | Nexus `type` |
|---|---|
| `character` (player-facing PC sheet found in a GM's world - rare but exportable) | `character` |
| everything else (`npc`, `hazard`, `loot`, `vehicle`) | `npc` |

`hazard`/`vehicle`/`loot`-typed actors are structurally closer to "npc" than
any other Nexus type in v1 - they still get a stat-block-shaped draft. A
future pass could split `hazard`→`encounter` if that distinction matters to
whoever reviews the drafts; not worth a special case until someone hits it.

| `NPCFrontmatter` field | Foundry source |
|---|---|
| `name` | `actor.name` |
| `ancestry` | `actor.system.details.ancestry.name` if present, else `"none"` |
| `char_class` | `actor.system.details.class.name` if present, else `"none"` |
| `level` | `actor.system.details.level.value`, clamped to `[1, 20]` |
| `background` | `actor.system.details.background.name` if present, else `""` |
| `abilities` | `actor.items[]` entries where `item.type == "action"` or `"feat"`, name only, deduped |
| `description` | `actor.system.details.biography.value` (HTML), converted to Markdown - see §HTML conversion |
| `tags` | `actor.system.traits.value[]` (PF2e trait list) + Foundry `actor.type` itself as one tag |

Draft body (skeleton, matches the existing NPC draft shape agents already
write): Description (from `biography.value`) → Equipment (flat list from
`actor.items[]` names, grouped by Foundry item type - README scope cut: list
only, not individual entities) → DM Notes (empty, human fills in).

`str_mod`/`dex_mod`/etc.: PF2e stores these as flat modifiers already
(`system.abilities.str.mod`) - copied 1:1, no derivation needed, unlike the
lore agent's LLM-generated `NPCLLMOutput` which invents them from scratch.

Portrait/token image (`actor.img`, `actor.prototypeToken.texture.src`): see
§Images below - not written into the draft's own frontmatter (no `img`
field on `EntityFrontmatter`); it re-enters the pipeline as its own image
draft and gets its own `source`, linked back only by both drafts sharing the
same `source: ["foundry:{world title}"]` tag - not a hard relationship
(scope cut, see README).

## Item (unowned, `data/items.db` only) → item / artifact

Only documents in `items.db` are mapped - an actor's *embedded* inventory
(`actor.items[]`) is never turned into a standalone entity (README scope
cut).

| Foundry `item.type` (pf2e) | Nexus `type` |
|---|---|
| `treasure` | `artifact` if `item.system.rarity` is `rare`/`unique`, else `item` |
| everything else (`weapon`, `armor`, `consumable`, `equipment`, `backpack`, ...) | `item` |

| `EntityFrontmatter` field | Foundry source |
|---|---|
| body text | `item.system.description.value` (HTML) → Markdown |
| `tags` | `item.system.traits.value[]` + `item.type` + rarity (if present and not `common`) |

## JournalEntry → lore (folder-hinted override)

Foundry journal entries have no `type` of their own beyond their pages'
content type - the vault's `type` field has to come from a heuristic:

| Journal's Foundry folder name contains (case-insensitive substring) | Nexus `type` |
|---|---|
| `npc`, `character` | `npc` |
| `location`, `place`, `map` | `location` |
| `quest`, `hook` | `quest` |
| `faction`, `organization`, `guild` | `faction` |
| *(no match, or no folder)* | `lore` (default) |

Body: every page where `page.type == "text"` is converted (`page.text.value`
HTML → Markdown) and concatenated under a `## {page.name}` heading, in the
journal's own page order (`page.sort`). Pages of type `image`/`video`/`pdf`
are skipped for body text; an `image`-type page's `page.src` is queued as an
image (§Images) instead.

`tags`: `[]` unless the folder-hint matched, in which case the matched
keyword itself is added as one tag (e.g. a `quest`-typed one gets `tags:
["quest"]`) - thin, but non-empty tags is a structural invariant
(`assertDraftInvariants` in this repo's test suite checks it), and an empty
guess is worse than a one-word one.

## Scene → image only (no draft)

Scenes do not get a `01-Processing` draft. `scene.background.src` (v11+
`background`) or `scene.img` (older) - whichever is present - is queued as
an image (§Images below). If neither is set (a scene with no background
image, e.g. a purely token-based encounter grid), the scene document is
skipped entirely and counted in `skipped`.

## Images (actors, items, journal image-pages, scenes)

Any of the paths above that resolve to an in-zip asset (not a Foundry core
icon reference like `icons/creatures/...` - those aren't in the export and
aren't campaign art) gets copied into:

```
00-Inbox/images/foundry-import/<world-slug>/<original-filename>
```

Filename collisions across different source documents get the same
numeric-suffix bump as everywhere else in the pipeline. From this point the
file is indistinguishable from a manual drag-and-drop - normal
`ingestion` → `vision` pipeline picks it up on the next cycle(s), gets its
own `01-Processing` draft with vision-derived `type`/`ancestry`/`tags`/etc.
This worker does **not** try to pre-fill vision's output from Foundry's
metadata (e.g. seeding `ancestry` from the actor's own ancestry field) -
keeping the image pipeline's contract exactly as it is for every other image
source is worth more than a small head start on tags the vision agent
already derives reliably today.

## HTML → Markdown conversion

Foundry description/biography fields are stored as rich-text HTML
(TinyMCE/ProseMirror output - `<p>`, `<strong>`, `<em>`, `<ul>/<li>`,
`<table>`, inline `@UUID[...]` Foundry entity links). v1 conversion:

- `<p>`, `<br>` → paragraph breaks.
- `<strong>`/`<b>`, `<em>`/`<i>` → `**bold**`/`*italic*`.
- `<ul>/<li>`, `<ol>/<li>` → `-`/`1.` lists.
- `<table>` → left as-is inside a fenced block if present (rare in
  descriptions; not worth a full HTML-table-to-Markdown-table converter for
  v1 - `ponytail: raw HTML table passthrough, add real conversion if a real
  export shows this matters`).
- Foundry's own `@UUID[Actor.abc123]{Display Name}` inline links → the
  display name as plain text, link stripped (it points at a Foundry-internal
  ID this vault has no notion of - not a `[[wikilink]]` candidate, since
  README already scopes out auto-relationships).
- Everything else: strip tags, keep text content.

No new dependency needed - this is a narrow, known-shape subset
(TinyMCE/ProseMirror's actual output vocabulary is small), handled with
stdlib `html.parser`. A general HTML-to-Markdown library would be climbing
past where the ladder stops for this input shape.
