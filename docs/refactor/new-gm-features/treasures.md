# Treasures & Lore - Page Spec

**Route:** `/gm/treasures` · **Icon:** `Gem` · **Accent:** teal/orange
**Archetype:** Entity Collection ([README.md](README.md#the-entity-collection-page-archetype))
**Types:** `item` · `artifact` · `lore` · **Guide:** §6

> "Lore and loot are the reward for paying attention. Deliver them through play,
> not lectures."

Entity Collection specialized to depth. Deltas only.

---

## Delta 1 - Types & chips

`item`/`artifact` render orange, `lore` renders teal. `+ New ▾` lists all three.

## Delta 2 - Build guidance strip (§6)

- [ ] **Rewards that hook** - the best treasure creates the next adventure
- [ ] **Signature items / artifacts** tied to factions or history
- [ ] **History the party can *discover*** - in ruins, NPC mouths, items
- [ ] **Mysteries with answers** - plant questions early, know the answers
- [ ] **Consistent internal logic** - magic, gods, money: pick rules, hold them

Rollup: "4 items · 2 hooking · 3 lore entries · 1 open mystery".

## Delta 3 - Vital-info field set (create skeleton + editor sections)

Item/artifact skeleton:

```markdown
## Effect
> What it does.

## Origin
> Where it came from.

## Desire
- **Who wants it:** [[ ]]   (NPC/faction)

## Hook
> The story it carries - the next adventure it creates.

## Price / catch
> The cost or curse.

## Related
```

Lore skeleton:

```markdown
## The question
> What mystery this plants.

## The answer
> Known to the GM even if players never reach it.

## How it's discovered
- In ruins / NPC / item: [[ ]]

## Related
```

## Delta 4 - Lore-specific behavior

- **Mystery tracker:** `lore` entries pair a **question** and an **answer**. A
  lore entry with a question but no answer shows an amber "unanswered" chip (the
  guide's "mysteries with answers"). The page lists open mysteries first.
- **Reveal channel:** every lore/item should link to *how* it's discovered (a
  location, NPC, or item). Unlinked lore → "wall of text" amber chip ("reveal
  lore as a reward, never as a wall of text").

## Delta 5 - Item-specific behavior

- **Hook flag:** an item whose `hook` creates a downstream quest shows a
  "→ quest" link; items can be set as a quest **reward** (back-reference from
  `/gm/quests`). Item linking rule: item → quest or owner NPC.
- **Signature** boolean for artifacts tied to a faction/history; pins to top.

## Delta 6 - Card

Card adds: who-wants-it avatar · a "hooks → {quest}" chip when the item seeds a
quest · for lore, a Q/A pill (answered/unanswered). Items with no owner and no
quest link → amber orphan chip.

## Delta 7 - Filters

Quick toggles: **Unowned** (no owner/quest), **Hooking** (creates a quest),
**Signature**, **Unanswered** (lore only), **Open mystery**. Sort by Type then
Updated.

## Delta 8 - Generate-with-AI seed

`lore` agent seed:

> "Create a signature item for {setting.pitch} tied to {a faction or the central
> tension}: what it does, where it came from, who wants it back, the hook it
> carries (the next adventure), and its price or catch."

## Inherited

All table/filter/sort/action/state behavior from the archetype.
