# Quests & Story — Page Spec

**Route:** `/gm/quests` · **Icon:** `ScrollText` · **Accent:** yellow
**Archetype:** Entity Collection ([README.md](README.md#the-entity-collection-page-archetype))
**Types:** `quest` · `event` · `timeline` · **Guide:** §4

> "Don't write a plot the party must follow. Write situations they must respond
> to."

Entity Collection specialized to the plot. Deltas only.

---

## Delta 1 — Types & chips

`quest`, `event`, `timeline` — all yellow. `+ New ▾` lists all three.

## Delta 2 — Build guidance strip (§4)

- [ ] **An opening hook** dropping the party into trouble in the first 15 min
- [ ] **3+ quest threads** of different shapes: a clear job · a mystery · a moral choice
- [ ] **Stakes the party cares about** (the innkeeper, not "the world")
- [ ] **A ticking clock** — a deadline / advancing threat
- [ ] **Branches, not rails** — ≥2 ways each quest can go
- [ ] **A campaign timeline** of events that happen regardless of the party

Rollup: "hook ✓ · 3 threads (job/mystery/—) · 1 clock".

## Delta 3 — Vital-info field set (create skeleton + editor sections)

```markdown
## Hook
> How the party hears of it.

## Patron
- **Who wants it done:** [[ ]]   (NPC)

## Place
- **Where it happens:** [[ ]]   (location)

## Obstacle
-

## Stakes
> Why the party cares — concrete, not abstract.

## Clock
- **Deadline / what gets worse:**

## Branches
- **Path A:**
- **Path B:**

## Reward
- [[ ]]   (item the reward hooks the next adventure)

## If ignored
> What happens if the party walks away.

## Related
```

## Delta 4 — Quest shape & the Hook flag

- Each quest carries a **shape** tag: `job` · `mystery` · `moral`. The build
  strip wants all three present; the page shows which shapes are missing.
- An **Opening hook** boolean flags the one quest that starts the campaign; it
  pins to the top and feeds readiness check #6 ("one hook + two threads").
- A quest with **no branches** (only one path) shows an amber "rail" chip — the
  guide's "branches, not rails."

## Delta 5 — Timeline view (pillar-special)

Beyond grid/table, a **Timeline lane** view: `event`/`timeline` entities laid on
a horizontal time axis (the guide's "campaign timeline of events that happen
regardless of the party"). Drag to reorder/redate; `quest` clocks overlay as
markers so the GM sees deadlines against world events. Dates ISO `YYYY-MM-DD`.

## Delta 6 — Quest-specific card

Card adds: shape chip (job/mystery/moral) · patron avatar · a clock badge
(deadline) · reward link. Missing patron **or** location → amber chip (the quest
linking rule: quest → NPC + location). Reward links to a `treasures` item.

## Delta 7 — Filters

Quick toggles: **Opening hook**, **No clock** (no urgency = "a chore"),
**Rail** (single branch), **Unstaked** (no stakes section), by **shape**.
Sort adds **Deadline**.

## Delta 8 — Generate-with-AI seed

`lore` agent seed:

> "Create a {shape} quest for {setting.pitch}: a hook, the patron (an existing
> NPC), where it happens (an existing location), the obstacle, concrete stakes,
> a ticking clock, two branches, a reward, and what happens if ignored."

## Inherited

All table/filter/sort/action/state behavior from the archetype.
