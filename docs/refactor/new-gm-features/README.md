# GM Workspace Refactor — Page Specs

**Purpose:** split the single `/gm` "Campaign Workshop" hub into a set of
focused, fully managed pages — one per campaign-building domain — so a Game
Master can run an entire campaign setting end to end without leaving the
dashboard. Each page spec below is UI/UX-level (ideas, buttons, actions, lists,
tables, filters, states), grounded in the existing pipeline, agents, and APIs.

These docs are a **specification**, not an implementation. They describe what a
user sees and does. Where a capability already exists in code it is named;
where it does not it is tagged **NEW**.

---

## Page map

| Route | Page | Entity `type`s | Spec |
|-------|------|----------------|------|
| `/gm` | Campaign Setting (replaces the hub) | — (cross-cutting) | [campaign.md](campaign.md) |
| `/gm/npcs` | Characters & NPCs | `npc` `character` | [npcs.md](npcs.md) |
| `/gm/places` | World & Places | `location` `city` `village` `dungeon` | [places.md](places.md) |
| `/gm/factions` | Factions & Powers | `faction` `organization` `religion` | [factions.md](factions.md) |
| `/gm/quests` | Quests & Story | `quest` `event` `timeline` | [quests.md](quests.md) |
| `/gm/bestiary` | Bestiary | `creature` `monster` `encounter` | [bestiary.md](bestiary.md) |
| `/gm/treasures` | Treasures & Lore | `item` `artifact` `lore` | [treasures.md](treasures.md) |
| `/gm/wiki` | Knowledge Wiki | all (read/link) | [wiki.md](wiki.md) |

Unchanged, already-built pages that these link to: `/gm/review`,
`/gm/view/[id]`, `/gm/view/[id]/token`, `/gm/inbox`, `/gm/tokens`, `/gm/chat`.

### Sidebar

The `GAME MASTER` nav group grows to (in build order, matching the guide):

```
Campaign      /gm           Dices
Places        /gm/places    Map
NPCs          /gm/npcs      Users
Factions      /gm/factions  Flag
Quests        /gm/quests    ScrollText
Bestiary      /gm/bestiary  Skull
Treasures     /gm/treasures Gem
Wiki          /gm/wiki      BookOpen
Review        /gm/review    CheckSquare
Inbox         /gm/inbox     Image
Tokens        /gm/tokens    CircleDot
Agent Chat    /gm/chat      MessageSquare
```

---

## The "Entity Collection Page" archetype

`npcs`, `places`, `factions`, `quests`, `bestiary`, and `treasures` are all the
**same page archetype** specialized to one pillar. This archetype is defined
once here; each pillar spec lists only its **deltas** (its types, its
field set, its pillar-specific actions). Read this section first.

### Concept

One screen to manage every entity in a pillar — drafts (`01-Processing`) and
canon (`02-Library`) side by side — create new ones from scratch or from an
agent, edit inline, and promote to canon. It is the pillar's slice of the vault
made directly actionable.

### Layout

```
┌ PageHeader: icon · title · "{N} entities · {d} drafts · {c} canon" ────────┐
│                                              [+ New ▾] [Generate with AI] │
├ Build guidance strip (collapsible) ───────────────────────────────────────┤
│  the pillar's checklist from campaign-setting-guide.md (the "build" items) │
├ Filter bar ───────────────────────────────────────────────────────────────┤
│  [type ▾] [origin ▾] [status ▾] [⚲ search]            [grid|table] [sort ▾]│
├ Collection ───────────────────────────────────────────────────────────────┤
│  card grid (default) OR table — see below                                  │
└────────────────────────────────────────────────────────────────────────────┘
```

### Data source

- Drafts: `readReviewItems()` filtered to the pillar's `type`s (origin `draft`).
- Canon: `readLibraryItems()` filtered the same way (origin `canon`).
- Merge by `id`; **canon wins** on collision (same rule as today's `/gm` hub).
- Served by **NEW** `GET /api/gm/collection?pillar=<key>` (thin wrapper over the
  two existing readers), or reuse `/api/review` + a canon endpoint.

### Card (grid view, default)

Per entity: token/type-chip thumbnail · `id` · type badge · origin badge
(`draft`/`canon`) · quality `Q{n}` · `{N} new` ribbon if unreviewed draft ·
one-line excerpt · relationship count. Whole card links to:
- draft → `/gm/view/{id}` (the existing editor)
- canon → `/gm/wiki/{id}` (read view) with an "Edit copy" affordance.

Hover reveals quick actions (icon buttons, per `gm-ui-guidelines.md`):
Promote (drafts), Flag/reprocess, Generate token (portrait/body only), Archive.

### Table view (toggle)

| Col | Source | Notes |
|-----|--------|-------|
| ▢ | selection | bulk actions |
| Token | `tokenPath` | 28px circle or type-chip fallback |
| ID | `id` | mono, links to editor |
| Type | `type` | colored badge (`BadgeSelect` inline-editable) |
| Origin | draft/canon | badge |
| Quality | `quality` | `QualityBar` mini |
| Status | `status` | badge |
| Tags | `tags` | first 3 + `+n` |
| Links | `relationships.length` | number; 0 = ⚠ orphan |
| Updated | `updated` | relative |
| ⋯ | actions | row menu |

Sortable by every column. Sticky header. The orphan flag (`Links = 0`) is the
vault's "no orphans" rule surfaced inline.

### Filters

`type` (the pillar's subset, default all) · `origin` (all/draft/canon) ·
`status` (draft/review/approved/archived) · `search` (id + excerpt + tags) ·
quick toggles: **Needs review** (unreviewed drafts), **Orphans** (no
relationships), **No token** (portrait/body types missing a token).

### Sort

Updated (default) · Quality · Name · Status · Most-linked.

### Primary actions (header)

1. **`+ New ▾`** — **NEW** `POST /api/gm/create`. Dropdown of the pillar's
   `type`s. Creates a blank draft in `01-Processing` with standard frontmatter
   (`status: draft`, `quality: 0`, `reviewed: false`, today's `created`/
   `updated`, empty `tags`/`source`/`relationships`) and a **body skeleton
   pre-filled from the pillar's "Vital info" list** in
   `campaign-setting-guide.md`. Routes straight into `/gm/view/{id}`.
2. **`Generate with AI`** — opens the `lore` agent (existing `/api/gm/chat`,
   `save: true`) seeded with a pillar-appropriate prompt; the saved draft lands
   in `01-Processing` and appears in the collection.

### Per-entity actions (reuse existing endpoints)

| Action | Endpoint | Availability |
|--------|----------|--------------|
| Open / edit | `/gm/view/{id}` | drafts |
| Promote to canon | `POST /api/gm/approve` | drafts, sets quality |
| Reject (q→1) | `POST /api/gm/reject` | drafts |
| Flag / reprocess | `POST /api/gm/flag` | drafts |
| Archive | `POST /api/gm/archive` | both |
| Rename slug | `POST /api/gm/rename` | drafts |
| Edit metadata | `POST /api/gm/edit` | drafts |
| Generate token | `POST /api/gm/token/generate` | portrait/body sources |

Bulk (table selection): Promote, Flag, Archive, Add tag, Add relationship.

### States

- **Empty (no entities):** centered prompt — "No {pillar} yet" + two CTAs:
  `+ New` and "Drop sources in the Inbox →" (`/gm/inbox`).
- **Empty (filtered out):** "No entities match — clear filters".
- **Loading:** spinner panel (matches `/gm/review`).
- **Error:** toast, bottom-center, auto-dismiss ~3s (`gm-ui-guidelines.md` §5).

### Pillar deltas (what each spec overrides)

1. The `type` set + type-chip colors.
2. The build-guidance checklist text.
3. The "Vital info" field set used for the create skeleton **and** as the
   editor's structured form sections.
4. Any pillar-special widget (faction clock, quest clock, encounter terrain).

---

## Shared conventions (all pages)

- **Theme tokens only** — `surface`/`surface-1..4`, `primary`, `success`,
  `danger`, `warning`, `zinc-*`. No raw hex. (`gm-ui-guidelines.md` §2.)
- **Components to reuse:** `PageHeader`, `Tip`, `QualityBar`, `QualityPicker`,
  `TagEditor`, `RelationshipEditor`, `BadgeSelect`, `ReviewCard`, `AutoRefresh`,
  the `ActionBtn` icon-button pattern.
- **Editor:** all "edit one entity" deep-links go to the existing
  `/gm/view/{id}` (`ItemDetailView`) — pages do not re-implement editing.
- **Feedback:** transient toasts, not sticky status. One toast at a time.
- **Type → color** (existing map): cast=blue, world=green, powers=purple,
  story=yellow, bestiary=red, treasures=orange/teal.
- **No agent self-approval:** `reviewed: true` / promotion is human-only; AI
  actions only ever write to `01-Processing`.

## New endpoints these specs assume

| Endpoint | Used by | Purpose |
|----------|---------|---------|
| `POST /api/gm/create` | every collection page, campaign | blank draft from skeleton |
| `GET /api/gm/collection?pillar=` | collection pages | merged draft+canon list |
| `GET /api/gm/readiness` | campaign | computed readiness check |
| `GET /api/gm/graph` | wiki | nodes + `[[wikilink]]` edges |
| `POST /api/gm/campaign` | campaign | create/update a `03-Campaigns` setting |

Everything else (`approve`, `reject`, `flag`, `edit`, `content`, `rename`,
`archive`, `chat`, `token/*`, `upload-image`) already exists.
