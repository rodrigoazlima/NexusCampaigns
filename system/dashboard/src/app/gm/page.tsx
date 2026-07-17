export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems } from '@/lib/vault'
import type { ReviewItem } from '@/lib/types'
import Link from 'next/link'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import VaultImage from '@/components/shared/VaultImage'
import {
  Dices, Map as MapIcon, Users, Flag, ScrollText, Skull, Gem,
  Inbox, CircleDot, MessageSquare, ArrowRight, Sparkles,
} from 'lucide-react'

// A "campaign building block" - each pillar groups the entity types a Game
// Master actually thinks in while building a world. Order = the order you
// usually build a campaign: a place, the people in it, who's fighting, the
// plot, the threats, then the depth that ties it together.
const PILLARS = [
  { key: 'world', label: 'World & Places', icon: MapIcon, accent: 'text-green-400', ring: 'border-green-500/20 hover:border-green-500/40',
    types: ['location', 'city', 'village', 'dungeon'], hint: 'The stage - where your story happens' },
  { key: 'cast', label: 'Characters & NPCs', icon: Users, accent: 'text-blue-400', ring: 'border-blue-500/20 hover:border-blue-500/40',
    types: ['npc', 'character'], hint: 'The cast - motivations, secrets, the people who drive play' },
  { key: 'powers', label: 'Factions & Powers', icon: Flag, accent: 'text-purple-400', ring: 'border-purple-500/20 hover:border-purple-500/40',
    types: ['faction', 'organization', 'religion'], hint: 'The conflict - who wants what, and why' },
  { key: 'story', label: 'Quests & Story', icon: ScrollText, accent: 'text-yellow-400', ring: 'border-yellow-500/20 hover:border-yellow-500/40',
    types: ['quest', 'event', 'timeline'], hint: 'The plot - hooks, stakes, what happens next' },
  { key: 'bestiary', label: 'Bestiary', icon: Skull, accent: 'text-red-400', ring: 'border-red-500/20 hover:border-red-500/40',
    types: ['creature', 'monster', 'encounter'], hint: 'The challenges - what the party fights' },
  { key: 'lore', label: 'Treasures & Lore', icon: Gem, accent: 'text-teal-400', ring: 'border-teal-500/20 hover:border-teal-500/40',
    types: ['item', 'artifact', 'lore'], hint: 'Reward & depth - history, myth, treasure' },
] as const

type Entry = ReviewItem & { origin: 'draft' | 'canon' }

export default async function GMHubPage() {
  const drafts = readReviewItems().map((i): Entry => ({ ...i, origin: 'draft' }))
  const canon = readLibraryItems().map((i): Entry => ({ ...i, origin: 'canon' }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, Entry>()
  for (const e of [...drafts, ...canon]) byId.set(e.id, e)
  const all = [...byId.values()]

  const known = new Set<string>(PILLARS.flatMap((p) => p.types))
  const bucket = (types: readonly string[]) =>
    all
      .filter((e) => types.includes(e.type))
      .sort((a, b) => (b.updated ?? '').localeCompare(a.updated ?? ''))

  const unreviewed = all.filter((e) => e.origin === 'draft' && !e.reviewed).length
  const uncategorized = all.filter((e) => !known.has(e.type)).length

  const href = (e: Entry) =>
    e.origin === 'draft' ? `/gm/view/${e.uuid || encodeURIComponent(e.id)}` : '/library'

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Dices}
        title="Campaign Workshop"
        subtitle={`${all.length} building blocks${uncategorized ? ` · ${uncategorized} unsorted` : ''} · shape raw drafts into your world`}
      />

      {/* Needs-you banner: the only review signal that matters here */}
      {unreviewed > 0 && (
        <Link
          href="/gm/review"
          className="panel flex items-center gap-3 p-3 mb-6 border border-warning/30 bg-warning/5 hover:bg-warning/10 transition-colors group"
        >
          <Sparkles size={18} className="text-warning flex-shrink-0" />
          <span className="text-sm text-zinc-200 flex-1">
            <span className="font-semibold text-warning">{unreviewed}</span> fresh{' '}
            {unreviewed === 1 ? 'draft is' : 'drafts are'} waiting for your review
          </span>
          <ArrowRight size={16} className="text-zinc-500 group-hover:text-warning group-hover:translate-x-0.5 transition-all" />
        </Link>
      )}

      {/* Campaign pillars */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        {PILLARS.map((p) => {
          const items = bucket(p.types)
          const waiting = items.filter((e) => e.origin === 'draft' && !e.reviewed).length
          const Icon = p.icon
          return (
            <div key={p.key} className={`panel border ${p.ring} transition-colors flex flex-col`}>
              {/* Pillar header */}
              <div className="flex items-start gap-3 p-4 pb-3">
                <div className="w-10 h-10 rounded-lg bg-surface-3 border border-surface-3 flex items-center justify-center flex-shrink-0">
                  <Icon size={20} className={p.accent} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="text-sm font-semibold text-zinc-100">{p.label}</span>
                    <span className={`text-lg font-mono font-bold ${p.accent}`}>{items.length}</span>
                    {waiting > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-warning/15 text-warning font-medium">
                        {waiting} new
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-zinc-500 mt-0.5">{p.hint}</p>
                </div>
              </div>

              {/* Item previews - click straight through, no detour */}
              <div className="flex-1 border-t border-surface-3/60">
                {items.length === 0 ? (
                  <Link
                    href="/gm/inbox"
                    className="block px-4 py-5 text-xs text-zinc-600 hover:text-zinc-400 transition-colors text-center"
                  >
                    Nothing here yet - drop sources in the Inbox →
                  </Link>
                ) : (
                  items.slice(0, 4).map((e) => (
                    <Link
                      key={e.id}
                      href={href(e)}
                      className="flex items-center gap-2.5 px-4 py-2 hover:bg-surface-2 border-b border-surface-3/40 last:border-0 group"
                    >
                      <VaultImage path={e.tokenPath} type={e.type} className="w-7 h-7 rounded object-cover flex-shrink-0 bg-surface-3" alt="" />
                      <div className="flex-1 min-w-0">
                        <div className="text-xs text-zinc-200 truncate group-hover:text-white">{e.id}</div>
                        <div className="text-[11px] text-zinc-600 truncate">{e.excerpt || '-'}</div>
                      </div>
                      {e.origin === 'canon' && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-success/10 text-success flex-shrink-0">canon</span>
                      )}
                    </Link>
                  ))
                )}
              </div>

              {/* Footer */}
              {items.length > 4 && (
                <Link
                  href="/gm/review"
                  className="px-4 py-2 text-[11px] text-zinc-500 hover:text-zinc-300 border-t border-surface-3/60 flex items-center gap-1 transition-colors"
                >
                  +{items.length - 4} more in Review <ArrowRight size={11} />
                </Link>
              )}
            </div>
          )
        })}
      </div>

      {/* Workshop tools */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { href: '/gm/inbox', icon: Inbox, label: 'Inbox', sub: 'raw sources' },
          { href: '/gm/tokens', icon: CircleDot, label: 'Tokens', sub: 'portraits & frames' },
          { href: '/gm/chat', icon: MessageSquare, label: 'Agent Chat', sub: 'lore · wiki · vision' },
        ].map((t) => {
          const Icon = t.icon
          return (
            <Link
              key={t.href}
              href={t.href}
              className="panel p-3 flex items-center gap-3 hover:bg-surface-2 border border-surface-3 hover:border-surface-4 transition-colors"
            >
              <Icon size={18} className="text-zinc-400 flex-shrink-0" />
              <div className="min-w-0">
                <div className="text-xs font-semibold text-zinc-200 truncate">{t.label}</div>
                <div className="text-[10px] text-zinc-600 truncate">{t.sub}</div>
              </div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
