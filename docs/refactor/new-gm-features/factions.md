# Factions & Powers - Page Spec

**Route:** `/gm/factions` · **Icon:** `Flag` · **Accent:** purple
**Archetype:** Entity Collection ([README.md](README.md#the-entity-collection-page-archetype))
**Types:** `faction` · `organization` · `religion` · **Guide:** §3

> "Factions turn a static map into a pressure cooker. They act whether or not
> the party is watching."

Entity Collection specialized to conflict. Deltas only.

---

## Delta 1 - Types & chips

`faction`, `organization`, `religion` - all purple. `+ New ▾` lists all three.

## Delta 2 - Build guidance strip (§3)

- [ ] **2–4 factions** with clashing goals (overlap → friction → plot)
- [ ] Each needs: goal · method · **leader (NPC)** · **stronghold (location)** · a resource
- [ ] **A faction clock** - what it does over coming weeks if uninterrupted
- [ ] **Where the party fits** - who courts them, who they threaten
- [ ] **A religion / belief system** if it matters

Rollup: "3 factions · 2 with clocks · 1 leaderless".

## Delta 3 - Vital-info field set (create skeleton + editor sections)

```markdown
## Goal
> What this faction wants.

## Method
> How it pursues the goal.

## Leadership
- **Leader:** [[ ]]   (NPC)

## Seat of power
- **Stronghold:** [[ ]]   (location)

## Resource / leverage
-

## Rivalry
- **At war with:** [[ ]]

## Clock - advances when ignored
- [ ] Step 1:
- [ ] Step 2:
- [ ] Step 3:

## Related
```

## Delta 4 - The Faction Clock widget (pillar-special)

The signature feature of this page. Each faction card/row exposes a **clock**:
an ordered list of steps the faction takes if the party does nothing, with the
current step highlighted.

- Inline **Advance** / **Rewind** buttons move the clock between sessions
  ("Advance it between sessions" - the guide). Persists to frontmatter
  (`clock_step`) via `POST /api/gm/edit`.
- A page-level **Clocks board** view: all faction clocks stacked as horizontal
  progress tracks, so the GM sees the whole world's momentum at a glance and can
  advance several at once between sessions.
- A faction with **no clock** shows an amber "static - won't act" chip (fails
  the guide's "world feels alive" test and readiness check #4/#7).

## Delta 5 - Faction-specific card

Card adds: leader avatar (linked NPC token) · stronghold name · a 3-pip clock
indicator · "at war with" rival chip. Missing leader or stronghold → amber chip
(violates the faction linking rule: faction → NPC + location).

## Delta 6 - Filters

Quick toggles: **No clock**, **Leaderless** (no leader link), **No stronghold**,
**At war** (has a rivalry link). Sort adds **Clock progress**.

## Delta 7 - Generate-with-AI seed

`lore` agent seed:

> "Create a faction for {setting.pitch} that clashes with {existing faction or
> the central tension}. Give it a goal, method, a leader, a stronghold, a
> resource, a rival, and a 3-step clock describing what it does if the party
> ignores it."

## Inherited

All table/filter/sort/action/state behavior from the archetype.
