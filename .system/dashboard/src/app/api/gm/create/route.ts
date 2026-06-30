import { NextRequest, NextResponse } from 'next/server'
import { createDraft } from '@/lib/vault'

export const dynamic = 'force-dynamic'

// Body skeleton per type — pre-fills the editor's structured sections.
// Only the cast pillar (npc/character) is wired this phase; other pillars add
// their skeleton when their page lands.
const NPC_SKELETON = `## Identity
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
`

// bestiary.md Delta 3 — placed-fight skeleton vs. leaner stat-entity skeleton.
const ENCOUNTER_SKELETON = `## Composition
- **What & how many:** [[ ]] ×N

## Place
- **Where:** [[ ]]

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
`

const CREATURE_SKELETON = `## Appearance
-

## Behavior
-

## Signature ability
-

## Found
- **Where:** [[ ]]

## Drops
- **Drops or reveals:** [[ ]]

## Related
`

// factions.md Delta 3 — goal/method/leader/stronghold/resource/rival + clock.
const FACTION_SKELETON = `## Goal
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

## Clock — advances when ignored
- [ ] Step 1:
- [ ] Step 2:
- [ ] Step 3:

## Related
`

// places.md Delta 3 — purpose/control/affordances/sensory/secret/connections.
const PLACE_SKELETON = `## Purpose
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
- **Occupied by:** [[ ]]   (NPC/faction — no empty rooms)

## Related
`

// quests.md Delta 3 — hook/patron/place/obstacle/stakes/clock/branches/reward.
const QUEST_SKELETON = `## Hook
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
`

// event / timeline — leaner: when it happens, what changes, who's involved.
const EVENT_SKELETON = `## When
- **Date (ISO):**

## What happens
>

## Who's involved
- [[ ]]

## Consequence
> What changes in the world — happens whether or not the party acts.

## Related
`

// treasures.md Delta 3 — item/artifact: effect/origin/desire/hook/price.
const ITEM_SKELETON = `## Effect
> What it does.

## Origin
> Where it came from.

## Desire
- **Who wants it:** [[ ]]   (NPC/faction)

## Hook
> The story it carries — the next adventure it creates.

## Price / catch
> The cost or curse.

## Related
`

// treasures.md Delta 3 — lore: a planted question + the GM-known answer + reveal.
const LORE_SKELETON = `## The question
> What mystery this plants.

## The answer
> Known to the GM even if players never reach it.

## How it's discovered
- In ruins / NPC / item: [[ ]]

## Related
`

const SKELETONS: Record<string, string> = {
  npc: NPC_SKELETON,
  character: NPC_SKELETON,
  creature: CREATURE_SKELETON,
  monster: CREATURE_SKELETON,
  encounter: ENCOUNTER_SKELETON,
  faction: FACTION_SKELETON,
  organization: FACTION_SKELETON,
  religion: FACTION_SKELETON,
  location: PLACE_SKELETON,
  city: PLACE_SKELETON,
  village: PLACE_SKELETON,
  dungeon: PLACE_SKELETON,
  quest: QUEST_SKELETON,
  event: EVENT_SKELETON,
  timeline: EVENT_SKELETON,
  item: ITEM_SKELETON,
  artifact: ITEM_SKELETON,
  lore: LORE_SKELETON,
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export async function POST(req: NextRequest) {
  try {
    const { type, name } = (await req.json()) as { type?: string; name?: string }

    if (!type || !SKELETONS[type]) {
      return NextResponse.json({ error: 'unsupported or missing type' }, { status: 400 })
    }

    const slug = name ? slugify(name) : ''
    const id = slug ? `${type}-${slug}` : `${type}-untitled-${Date.now().toString(36)}`

    const filename = createDraft({ id, type, body: SKELETONS[type] })

    return NextResponse.json({ ok: true, id, filename })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
