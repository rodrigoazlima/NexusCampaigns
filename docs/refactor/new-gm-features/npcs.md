# Characters & NPCs — Page Spec

**Route:** `/gm/npcs` · **Icon:** `Users` · **Accent:** blue
**Archetype:** Entity Collection ([README.md](README.md#the-entity-collection-page-archetype))
**Types:** `npc` · `character` · **Guide:** §2

> "NPCs are the campaign. Plots are just what NPCs do to each other."

This page is the Entity Collection archetype specialized to the cast. Only the
deltas are below; everything else (table columns, filters, states, bulk
actions, create/promote/archive flow) is inherited from the archetype.

---

## Delta 1 — Types & chips

`npc`, `character`. Both render blue (`bg-blue-500/10 text-blue-400`). `+ New ▾`
offers: **NPC** (minor/recurring) and **Character** (major/PC-adjacent).

## Delta 2 — Build guidance strip (§2)

Collapsible checklist shown above the filter bar; each item is a live count
where measurable:

- [ ] A **quest-giver / patron** — points the party at trouble
- [ ] An **antagonist** with a goal (wins if the party does nothing)
- [ ] **2–3 neutral locals** the party will actually talk to
- [ ] Give each a **WANT** · the important ones a **SECRET**
- [ ] One **distinctive trait** each (the "limping notary")
- [ ] **Relationships between NPCs** — who hates/owes whom

A small "✓ patron · ✗ antagonist · 2/3 locals" rollup mirrors the readiness
inputs on the Campaign page.

## Delta 3 — Vital-info field set

Drives both the **create skeleton** (`POST /api/gm/create`) and the structured
form sections in the editor. NPC body skeleton:

```markdown
## Identity
- **Role / occupation:**
- **Appearance hook:**
- **Voice / mannerism:**

## Want
> What they want from the party or the world — the engine of every scene.

## Secret
> Something the party can discover that changes how they see them.

## Personality
- One line:

## Ties
- **Faction:** [[ ]]
- **Location:** [[ ]]
- **Offers the party:** hook / info / threat

## Related
```

The editor surfaces **Want** and **Secret** as first-class, highlighted blocks
(they are what readiness check #3 and the "make NPCs collide" guidance depend
on). An NPC with an empty **Want** shows an amber "needs a want" chip on its
card and in the table's Status column.

## Delta 4 — NPC-specific card

Cards lead with the **token portrait** (this pillar is the main token consumer).
Card face adds: a **want** one-liner (italic, truncated) under the id, and a
small lock icon if a **secret** is present (not its content). Quick action
**Generate token** is always visible here (portrait/body eligible).

## Delta 5 — NPC-specific filters & views

- Extra quick toggles: **No want**, **No secret**, **No token**, **Patron**,
  **Antagonist** (derived from a `role`/tag heuristic).
- Extra view: **Relationship lens** — a compact who-knows-whom mini-map for the
  filtered NPCs (reuses the wiki graph component scoped to cast). Surfaces the
  guide's "triangles, not lists" — three NPCs each wanting something from the
  other two. Read-only; "Open in Wiki →" for the full graph.

## Delta 6 — Generate-with-AI seed

The header **Generate with AI** opens the `lore` agent pre-seeded:

> "Create an NPC for {setting.pitch}. Give them a role, a concrete WANT, a
> SECRET, one distinctive trait, and ties to an existing faction and location.
> Output the NPC sheet only."

Saved to `01-Processing` (`save: true`), then appears in the collection as an
unreviewed draft. Existing `lore` agent already generates NPC sheets from
image + scenario; this is the text-first path.

## Inherited (for reference, not overridden)

Table columns, origin/status/type filters, sort, promote/reject/flag/archive/
rename, bulk actions, empty/loading/error states, deep-link to `/gm/view/{id}`.
See the archetype.
