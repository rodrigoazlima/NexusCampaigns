# World & Places - Page Spec

**Route:** `/gm/places` · **Icon:** `Map` · **Accent:** green
**Archetype:** Entity Collection ([README.md](README.md#the-entity-collection-page-archetype))
**Types:** `location` · `city` · `village` · `dungeon` · **Guide:** §1

> "The party needs a place to stand before they need a plot."

Entity Collection specialized to the stage. Deltas only.

---

## Delta 1 - Types & chips

`location`, `city`, `village`, `dungeon` - all green. `+ New ▾` lists all four.
An **Anchor** flag (boolean tag) marks the party's home base; the anchor pins to
the top of the collection and shows a "home" icon.

## Delta 2 - Build guidance strip (§1)

- [ ] **Anchor location** - one home base: name, mood, 3 notable spots, 1 problem
- [ ] **3–5 nearby places** reachable in a session (each: reason to go · something there · a danger)
- [ ] **A map** - even rough; distances create decisions
- [ ] **Sensory hooks** per place - one smell, one sound, one sight
- [ ] **Connect places to people** - every location links ≥1 NPC or faction

Rollup: "anchor ✓ · 4 nearby · 2 unlinked".

## Delta 3 - Vital-info field set (create skeleton + editor sections)

```markdown
## Purpose
> What this place is *for* in the story.

## Control
- **Who controls it:** [[ ]]

## What the party can do here
-

## Sensory hooks
- **Smell:**
- **Sound:**
- **Sight:**

## Secret
> One hidden thing.

## Connections
- **Leads to:** [[ ]]
- **Occupied by:** [[ ]]   (NPC/faction - no empty rooms)

## Related
```

The editor flags a location with no NPC/faction relationship as **"set
dressing"** (amber) - the guide's "an empty room is set dressing; an occupied
one is a scene."

## Delta 4 - Place-specific card & map view

- Cards use the **scene/battlemap image** as the thumbnail (this pillar's
  sources are environments, not portraits) - token actions are hidden here
  unless the source classified as portrait/body.
- Card adds a **link count to NPCs/factions** badge ("3 occupants").
- Extra view: **Map board** - a free-position canvas where place cards can be
  dragged to lay out rough geography and draw "leads-to" connectors. Saves
  positions to the setting frame (`03-Campaigns`). Read of the guide's "A map -
  even a rough one." (Lower priority; can ship after the list/table.)

## Delta 5 - Place-specific filters

Quick toggles: **Anchor**, **Unlinked** (no occupant - set dressing),
**Has battlemap** (a `battlemap-*` asset exists for it), **No sensory hooks**.

## Delta 6 - Generate-with-AI seed

`lore` agent seed:

> "Describe a {type} near {anchor.name} for {setting.pitch}: its purpose, who
> controls it, what the party can do there, three sensory hooks, one secret,
> and which existing NPC or faction occupies it."

## Inherited

All table/filter/sort/action/state behavior from the archetype.
