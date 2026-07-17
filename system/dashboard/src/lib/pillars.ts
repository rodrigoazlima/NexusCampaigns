import type { LucideIcon } from 'lucide-react'
import { Map as MapIcon, Users, Flag, ScrollText, Skull, Gem } from 'lucide-react'

// The six campaign-building pillars. Pure config (no fs) so both the server
// page and the client view can import it. `target` is the count-based "build
// first" goal used for the pillar progress bar - see campaign-setting-guide.md.
export interface Pillar {
  key: string
  label: string
  icon: LucideIcon
  accent: string
  types: string[]
  target: number
  href: string
  hint: string
}

export const PILLARS: Pillar[] = [
  { key: 'world', label: 'World & Places', icon: MapIcon, accent: 'text-green-400',
    types: ['location', 'city', 'village', 'dungeon'], target: 4, href: '/gm/places',
    hint: 'Anchor location + 3 nearby' },
  { key: 'cast', label: 'Characters & NPCs', icon: Users, accent: 'text-blue-400',
    types: ['npc', 'character'], target: 4, href: '/gm/npcs',
    hint: 'Patron · antagonist · 2–3 locals' },
  { key: 'powers', label: 'Factions & Powers', icon: Flag, accent: 'text-purple-400',
    types: ['faction', 'organization', 'religion'], target: 2, href: '/gm/factions',
    hint: '2–4 clashing factions w/ clocks' },
  { key: 'story', label: 'Quests & Story', icon: ScrollText, accent: 'text-yellow-400',
    types: ['quest', 'event', 'timeline'], target: 3, href: '/gm/quests',
    hint: 'Opening hook + 3 threads' },
  { key: 'bestiary', label: 'Bestiary', icon: Skull, accent: 'text-red-400',
    types: ['creature', 'monster', 'encounter'], target: 1, href: '/gm/bestiary',
    hint: 'Signature regional threat' },
  { key: 'lore', label: 'Treasures & Lore', icon: Gem, accent: 'text-teal-400',
    types: ['item', 'artifact', 'lore'], target: 2, href: '/gm/treasures',
    hint: 'Hook-creating rewards' },
]

export function pillarOf(type: string): string | null {
  return PILLARS.find((p) => p.types.includes(type))?.key ?? null
}
