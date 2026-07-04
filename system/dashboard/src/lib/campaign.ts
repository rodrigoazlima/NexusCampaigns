import fs from 'fs'
import matter from 'gray-matter'
import type { ReviewItem } from './types'
import { PILLARS, pillarOf } from './pillars'

// Server-side campaign readiness + progress computation. All the heuristics
// (which section counts as a "want" / a "clock") live here, not the UI, so they
// stay tunable — per campaign.md §5. ponytail: computed inline in the server
// page (no /api/gm/readiness endpoint); the page is force-dynamic + auto-refreshed.

export type Entry = ReviewItem & { origin: 'draft' | 'canon' }

export interface PillarStat {
  key: string
  count: number
  waiting: number   // unreviewed drafts
  pct: number       // build progress vs. pillar target (0–100)
}

export interface ReadinessCheck {
  id: string
  label: string
  ok: boolean
  detail: string
  fixHref: string
}

export interface WiringHealth {
  orphans: number
  factionClocks: number
  thread: string | null   // id of an entity linking across ≥3 pillars, if any
}

export interface CampaignData {
  pillars: PillarStat[]
  checks: ReadinessCheck[]
  wiring: WiringHealth
  unreviewed: number
  totals: { entities: number; drafts: number; canon: number }
}

interface Flags {
  bodyNonEmpty: boolean
  hasClock: boolean
  hasHook: boolean
  wantFilled: boolean
}

// A `## heading` section counts as "filled" only with real content — not empty
// and not a `>` blockquote (the create skeletons seed prompts as blockquotes).
// Same rule as vault.parseWantSecret / parseBestiary.
function sectionFilled(body: string, heading: string): boolean {
  const lines = body.split('\n')
  const start = lines.findIndex((l) => l.trim().toLowerCase() === `## ${heading}`.toLowerCase())
  if (start === -1) return false
  for (let i = start + 1; i < lines.length; i++) {
    const line = lines[i].trim()
    if (line.startsWith('## ')) break
    if (!line || line.startsWith('>')) continue
    if (line.replace(/^[-*]\s*/, '').replace(/\*\*/g, '').replace(/^[^:]*:\s*/, '')) return true
  }
  return false
}

function flagsFor(e: Entry): Flags {
  let body = ''
  try {
    body = matter(fs.readFileSync(e.filepath, 'utf-8')).content
  } catch {
    return { bodyNonEmpty: false, hasClock: false, hasHook: false, wantFilled: false }
  }
  const tags = e.tags.map((t) => t.toLowerCase())
  const hasClock =
    tags.includes('clock') || tags.includes('deadline') ||
    /##\s*(clock|advance|deadline|countdown)/i.test(body) ||
    /advanc\w*\b[^.\n]{0,30}\bignored/i.test(body)
  const hasHook = tags.includes('hook') || /##\s*hook/i.test(body)
  return {
    bodyNonEmpty: body.trim().length > 0,
    hasClock,
    hasHook,
    wantFilled: sectionFilled(body, 'Want'),
  }
}

const PLACE_TYPES = ['location', 'city', 'village', 'dungeon']
const FACTION_TYPES = ['faction', 'organization', 'religion']

export function buildCampaignData(drafts: Entry[], canon: Entry[]): CampaignData {
  // Merge by id, canon wins on collision (same rule as the /gm hub).
  const byId = new Map<string, Entry>()
  for (const e of [...drafts, ...canon]) byId.set(e.id, e)
  const all = [...byId.values()]

  const flags = new Map<string, Flags>()
  for (const e of all) flags.set(e.id, flagsFor(e))
  const f = (e: Entry) => flags.get(e.id)!

  const ofTypes = (types: string[]) => all.filter((e) => types.includes(e.type))

  // ── Pillar progress (§4) ────────────────────────────────────────────────
  const pillars: PillarStat[] = PILLARS.map((p) => {
    const items = ofTypes(p.types)
    const waiting = items.filter((e) => e.origin === 'draft' && !e.reviewed).length
    const pct = Math.min(100, Math.round((items.length / p.target) * 100))
    return { key: p.key, count: items.length, waiting, pct }
  })

  // ── Readiness checklist (§8) ────────────────────────────────────────────
  const places = ofTypes(PLACE_TYPES)
  const npcs = ofTypes(['npc', 'character'])
  const factions = ofTypes(FACTION_TYPES)
  const quests = all.filter((e) => e.type === 'quest')
  const timeline = all.filter((e) => e.type === 'timeline' || e.type === 'event')

  const scenes = [...places, ...timeline].filter((e) => f(e).bodyNonEmpty)
  const detailedPlaces = places.filter((e) => e.origin === 'canon' || e.quality >= 7)
  const npcsWithWants = npcs.filter((e) => f(e).wantFilled)
  const factionClocks = factions.filter((e) => f(e).hasClock)
  const clockEntities = all.filter((e) => f(e).hasClock)
  const hookQuests = quests.filter((e) => f(e).hasHook)

  const checks: ReadinessCheck[] = [
    {
      id: 'opening-scene', label: 'Opening scene described', fixHref: '/gm/places',
      ok: scenes.length >= 1,
      detail: scenes.length >= 1 ? `${scenes.length} place/event with a described scene` : 'No place or event has body text yet',
    },
    {
      id: 'detailed-place', label: 'One place detailed enough to improvise', fixHref: '/gm/places',
      ok: detailedPlaces.length >= 1,
      detail: detailedPlaces.length >= 1 ? `${detailedPlaces.length} canon / Q7+ place` : `${places.length} places, none canon or Q7+`,
    },
    {
      id: 'npc-wants', label: '3+ NPCs with wants', fixHref: '/gm/npcs',
      ok: npcsWithWants.length >= 3,
      detail: `${npcsWithWants.length}/3 NPCs have a filled WANT`,
    },
    {
      id: 'faction-pressure', label: 'A faction making things worse', fixHref: '/gm/factions',
      ok: factionClocks.length >= 1,
      detail: factionClocks.length >= 1 ? `${factionClocks.length} faction with a clock` : `${factions.length} factions, none with a clock`,
    },
    {
      id: 'clock', label: 'A clock exists', fixHref: '/gm/quests',
      ok: clockEntities.length >= 1,
      detail: clockEntities.length >= 1 ? `${clockEntities.length} entity with a clock/deadline` : 'Nothing gets worse if the party stalls',
    },
    {
      id: 'hook-threads', label: 'One hook + two threads', fixHref: '/gm/quests',
      ok: hookQuests.length >= 1 && quests.length >= 3,
      detail: `${hookQuests.length} hook · ${quests.length} quest${quests.length === 1 ? '' : 's'} (need 1 hook + 3 quests)`,
    },
    {
      id: 'world-moves', label: 'World moves without players', fixHref: '/gm/factions',
      ok: timeline.length >= 1 || factionClocks.length >= 1,
      detail: timeline.length >= 1 || factionClocks.length >= 1
        ? `${timeline.length} timeline/event · ${factionClocks.length} faction clock`
        : 'No timeline, event, or faction clock',
    },
  ]

  // ── Wiring health (§7) ──────────────────────────────────────────────────
  const orphans = all.filter((e) => e.relationships.length === 0).length

  const idToPillar = new Map<string, string | null>()
  for (const e of all) idToPillar.set(e.id, pillarOf(e.type))
  let thread: string | null = null
  let bestSpan = 2 // need ≥3 distinct pillars to count
  for (const e of all) {
    const spanned = new Set<string>()
    const own = pillarOf(e.type)
    if (own) spanned.add(own)
    for (const rel of e.relationships) {
      const target = rel.replace(/\[|\]/g, '').trim()
      const p = idToPillar.get(target)
      if (p) spanned.add(p)
    }
    if (spanned.size > bestSpan) { bestSpan = spanned.size; thread = e.id }
  }

  const draftCount = all.filter((e) => e.origin === 'draft').length
  return {
    pillars,
    checks,
    wiring: { orphans, factionClocks: factionClocks.length, thread },
    unreviewed: all.filter((e) => e.origin === 'draft' && !e.reviewed).length,
    totals: { entities: all.length, drafts: draftCount, canon: all.length - draftCount },
  }
}
