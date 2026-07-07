# Bestiary — Page Spec

**Route:** `/gm/bestiary` · **Icon:** `Skull` · **Accent:** red
**Archetype:** Entity Collection ([README.md](README.md#the-entity-collection-page-archetype))
**Types:** `creature` · `monster` · `encounter` · **Guide:** §5

> "Combat is a language for expressing the setting's dangers. Make fights say
> something."

Entity Collection specialized to the challenges. Deltas only.

---

## Delta 1 — Types & chips

`creature`, `monster`, `encounter` — all red. `+ New ▾` lists all three.
Distinction surfaced in UI: `creature`/`monster` are reusable stat entities;
`encounter` is a *placed* fight that links creatures to a location.

## Delta 2 — Build guidance strip (§5)

- [ ] **A signature threat** for the region ("you are *here*")
- [ ] **Encounters with a reason to exist** — guarding/hunting what?
- [ ] **Variety of pressure** — brute · swarm · social/avoidable · puzzle-creature
- [ ] **Terrain in every fight** — cover, hazards, verticality, escape routes
- [ ] **Non-combat outs** — talk past, sneak, bargain

Rollup: "signature ✓ · pressure variety 2/4 · 3 encounters, 1 flat".

## Delta 3 — Vital-info field set (create skeleton + editor sections)

Encounter skeleton:

```markdown
## Composition
- **What & how many:** [[ ]] ×N   (creature links)

## Place
- **Where:** [[ ]]   (location)

## Reason
> Why it's here, now — guarding/hunting what.

## Terrain & hazards
- **Cover / verticality / escape routes:**

## Goal
> Kill? Delay? Guard?

## Non-combat alternative
> Talk / sneak / bargain.

## Reward / reveal
- **Drops or reveals:** [[ ]]

## Related
```

Creature/monster skeleton is leaner: appearance, behavior, signature ability,
where it's found, what it drops.

## Delta 4 — Encounter-specific fields

- **Pressure type** tag: `brute` · `swarm` · `social` · `puzzle`. The build
  strip tracks variety; the page shows missing pressure types.
- **Signature** boolean — the regional threat; pins to top, feeds the Campaign
  page's "you are here" identity.
- An encounter with **no terrain** section → amber "flat fight" chip ("flat
  empty rooms make flat fights"). No non-combat alternative → "forced fight"
  chip ("players love a fight they chose").

## Delta 5 — Bestiary-specific card

Card uses the creature image as thumbnail (token actions available when the
source classified portrait/body). Adds: pressure-type chip · CR/difficulty if
present · place link (encounters) · "×N" composition count. Encounter cards link
through to their creatures and location.

## Delta 6 — Filters

Quick toggles: **Signature**, **Flat** (no terrain), **Forced** (no non-combat
out), by **pressure type**. Filter encounters by linked **location**.

## Delta 7 — Generate-with-AI seed

`lore` agent seed:

> "Design a {pressure} encounter for {location} in {setting.pitch}: composition
> (existing creatures), why it's there, the terrain and hazards, its goal, a
> non-combat alternative, and what it drops or reveals."

## Inherited

All table/filter/sort/action/state behavior from the archetype.
