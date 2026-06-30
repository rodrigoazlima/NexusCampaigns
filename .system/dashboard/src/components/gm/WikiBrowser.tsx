'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import type { LucideIcon } from 'lucide-react'
import type { ReviewItem } from '@/lib/types'
import { PILLARS } from '@/lib/pillars'
import PageHeader from '@/components/widgets/PageHeader'
import QualityBar from '@/components/widgets/QualityBar'
import { Tip } from './Tip'
import {
  BookOpen, Search, Link2, Share2, LayoutList, Table as TableIcon,
} from 'lucide-react'

export type WikiItem = ReviewItem & {
  origin: 'draft' | 'canon'
  pillar: string | null
}

// Pillar → chip classes. Mirrors the type-color map used across the GM hub.
const PILLAR_CHIP: Record<string, string> = {
  world: 'bg-green-500/10 text-green-400',
  cast: 'bg-blue-500/10 text-blue-400',
  powers: 'bg-purple-500/10 text-purple-400',
  story: 'bg-yellow-500/10 text-yellow-400',
  bestiary: 'bg-red-500/10 text-red-400',
  lore: 'bg-teal-500/10 text-teal-400',
}
const chipOf = (p: string | null) => PILLAR_CHIP[p ?? ''] ?? 'bg-surface-3 text-zinc-500'

const SELECT_CLS = 'text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors'

type Scope = 'all' | 'canon' | 'draft'

// id/tag/excerpt/type match → relevance score (higher = better). 0 = no match.
function score(i: WikiItem, q: string): number {
  if (!q) return 0
  const id = i.id.toLowerCase()
  if (id === q) return 100
  if (id.startsWith(q)) return 80
  if (id.includes(q)) return 60
  if (i.tags.some((t) => t.toLowerCase().includes(q))) return 40
  if (i.type.toLowerCase().includes(q)) return 30
  if (i.excerpt.toLowerCase().includes(q)) return 20
  return 0
}

// Read-and-navigate destination. Read view (/gm/wiki/{id}) is not built yet;
// canon → Library, drafts → existing editor. ponytail: link to what exists.
const hrefOf = (i: WikiItem) =>
  i.origin === 'draft' ? `/gm/view/${encodeURIComponent(i.id)}` : '/library'

export default function WikiBrowser({ items }: { items: WikiItem[] }) {
  const [search, setSearch] = useState('')
  const [scope, setScope] = useState<Scope>('all')
  const [pillars, setPillars] = useState<Set<string>>(new Set())
  const [orphansOnly, setOrphansOnly] = useState(false)
  const [untaggedOnly, setUntaggedOnly] = useState(false)
  const [sortBy, setSortBy] = useState('relevance')
  const [view, setView] = useState<'list' | 'table'>('list')

  const totalLinks = items.reduce((n, i) => n + i.relationships.length, 0)
  const orphans = items.filter((i) => i.relationships.length === 0).length

  const pillarCount = useMemo(() => {
    const m: Record<string, number> = {}
    for (const i of items) if (i.pillar) m[i.pillar] = (m[i.pillar] ?? 0) + 1
    return m
  }, [items])

  const togglePillar = (key: string) =>
    setPillars((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })

  const q = search.trim().toLowerCase()
  const filtered = useMemo(() => {
    const out = items
      .filter((i) => scope === 'all' || i.origin === scope)
      .filter((i) => pillars.size === 0 || pillars.has(i.pillar ?? ''))
      .filter((i) => !orphansOnly || i.relationships.length === 0)
      .filter((i) => !untaggedOnly || i.tags.length === 0)
      .filter((i) => !q || score(i, q) > 0)

    out.sort((a, b) => {
      if (sortBy === 'name') return a.id.localeCompare(b.id)
      if (sortBy === 'links') return b.relationships.length - a.relationships.length
      if (sortBy === 'updated') return (b.updated ?? '').localeCompare(a.updated ?? '')
      // relevance: search score when querying, else fall back to updated
      if (q) return score(b, q) - score(a, q)
      return (b.updated ?? '').localeCompare(a.updated ?? '')
    })
    return out
  }, [items, scope, pillars, orphansOnly, untaggedOnly, q, sortBy])

  // Group by pillar when browsing (no query); flat list when searching.
  const grouped = !q && view === 'list'
  const groups = useMemo(() => {
    if (!grouped) return null
    type Group = { key: string; label: string; Icon: LucideIcon; accent: string; rows: WikiItem[] }
    const out: Group[] = PILLARS
      .map((p) => ({ key: p.key, label: p.label, Icon: p.icon, accent: p.accent, rows: filtered.filter((i) => i.pillar === p.key) }))
      .filter((g) => g.rows.length > 0)
    const rest = filtered.filter((i) => !i.pillar)
    if (rest.length) out.push({ key: '_other', label: 'Uncategorized', Icon: BookOpen, accent: 'text-zinc-500', rows: rest })
    return out
  }, [grouped, filtered])

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={BookOpen}
        title="Knowledge Wiki"
        subtitle={`${items.length} entities · ${totalLinks} links · ${orphans} orphans`}
        actions={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-zinc-600" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search everything…"
                className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 pl-7 pr-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors w-56"
              />
            </div>
            <Tip label="Graph view — coming soon">
              <span className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-surface-3 text-zinc-600 border border-surface-3 cursor-not-allowed">
                <Share2 size={14} /> Graph
              </span>
            </Tip>
          </div>
        }
      />

      {/* Scope + sort + view */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex rounded border border-surface-3 overflow-hidden">
          {(['all', 'canon', 'draft'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setScope(s)}
              className={`px-3 py-1.5 text-xs capitalize transition-colors ${
                scope === s ? 'bg-primary/15 text-primary' : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded border border-surface-3 overflow-hidden">
            <button
              onClick={() => setView('list')}
              className={`p-1.5 ${view === 'list' ? 'bg-primary/15 text-primary' : 'text-zinc-500 hover:text-zinc-300'}`}
              aria-label="List view"
            ><LayoutList size={14} /></button>
            <button
              onClick={() => setView('table')}
              className={`p-1.5 ${view === 'table' ? 'bg-primary/15 text-primary' : 'text-zinc-500 hover:text-zinc-300'}`}
              aria-label="Table view"
            ><TableIcon size={14} /></button>
          </div>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className={SELECT_CLS}>
            <option value="relevance">Relevance</option>
            <option value="name">Name</option>
            <option value="links">Most-linked</option>
            <option value="updated">Updated</option>
          </select>
          <span className="text-xs text-zinc-600">{filtered.length} / {items.length}</span>
        </div>
      </div>

      <div className="flex gap-4">
        {/* Left rail: facets */}
        <aside className="w-44 flex-shrink-0 hidden md:block">
          <div className="panel p-2 sticky top-4">
            <div className="text-[10px] uppercase tracking-wide text-zinc-600 px-2 py-1">Pillars</div>
            {PILLARS.map((p) => {
              const Icon = p.icon
              const on = pillars.has(p.key)
              return (
                <button
                  key={p.key}
                  onClick={() => togglePillar(p.key)}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                    on ? 'bg-primary/10 text-primary' : 'text-zinc-400 hover:bg-surface-3'
                  }`}
                >
                  <Icon size={13} className={on ? 'text-primary' : p.accent} />
                  <span className="flex-1 text-left truncate">{p.label}</span>
                  <span className="text-[10px] text-zinc-600">{pillarCount[p.key] ?? 0}</span>
                </button>
              )
            })}
            <div className="border-t border-surface-3/60 my-1.5" />
            {([
              ['Orphans', orphans, orphansOnly, setOrphansOnly],
              ['Untagged', items.filter((i) => i.tags.length === 0).length, untaggedOnly, setUntaggedOnly],
            ] as const).map(([label, count, val, set]) => (
              <button
                key={label}
                onClick={() => set((v: boolean) => !v)}
                className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                  val ? 'bg-warning/10 text-warning' : 'text-zinc-400 hover:bg-surface-3'
                }`}
              >
                <span className="flex-1 text-left">{label}</span>
                <span className="text-[10px] text-zinc-600">{count}</span>
              </button>
            ))}
          </div>
        </aside>

        {/* Main: results */}
        <main className="flex-1 min-w-0">
          {items.length === 0 ? (
            <div className="panel p-12 text-center text-zinc-500 text-sm">
              Nothing in the Library yet — build entities in the pillar pages, then promote them here.
            </div>
          ) : filtered.length === 0 ? (
            <div className="panel p-12 text-center text-zinc-500 text-sm">No match — try a tag or a different term.</div>
          ) : view === 'table' ? (
            <WikiTable rows={filtered} />
          ) : grouped && groups ? (
            <div className="space-y-5">
              {groups.map((g) => (
                <div key={g.key}>
                  <div className="flex items-center gap-2 mb-2 px-1">
                    <g.Icon size={14} className={g.accent} />
                    <span className="text-xs font-semibold text-zinc-300">{g.label}</span>
                    <span className="text-[10px] text-zinc-600">{g.rows.length}</span>
                  </div>
                  <div className="panel divide-y divide-surface-3/40">
                    {g.rows.map((i) => <Row key={i.id} i={i} />)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="panel divide-y divide-surface-3/40">
              {filtered.map((i) => <Row key={i.id} i={i} />)}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

function Row({ i }: { i: WikiItem }) {
  const preview = i.tokenPath ?? i.source[0]
  const src = preview ? `/api/image?path=${encodeURIComponent(preview)}` : null
  const links = i.relationships.length
  return (
    <Link href={hrefOf(i)} className="flex items-center gap-3 px-3 py-2 hover:bg-surface-2 group">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" className="w-8 h-8 rounded object-cover bg-surface-3 flex-shrink-0" />
      ) : (
        <span className={`w-8 h-8 rounded flex items-center justify-center text-[9px] font-bold uppercase flex-shrink-0 ${chipOf(i.pillar)}`}>
          {i.type.slice(0, 3)}
        </span>
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-mono text-zinc-100 truncate group-hover:text-primary">{i.id}</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase ${chipOf(i.pillar)}`}>{i.type}</span>
          <span className={`text-[9px] px-1 py-0.5 rounded ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span>
        </div>
        <p className="text-[11px] text-zinc-600 truncate mt-0.5">{i.excerpt || '—'}</p>
      </div>
      <span className={`flex items-center gap-1 text-[11px] flex-shrink-0 ${links === 0 ? 'text-warning' : 'text-zinc-500'}`}>
        <Link2 size={11} /> {links}
      </span>
    </Link>
  )
}

function WikiTable({ rows }: { rows: WikiItem[] }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-zinc-500 border-b border-surface-3">
          <tr className="text-left">
            <th className="p-2 font-medium">Token</th>
            <th className="p-2 font-medium">ID</th>
            <th className="p-2 font-medium">Type</th>
            <th className="p-2 font-medium">Origin</th>
            <th className="p-2 font-medium w-28">Quality</th>
            <th className="p-2 font-medium">Tags</th>
            <th className="p-2 font-medium">Links</th>
            <th className="p-2 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => {
            const preview = i.tokenPath ?? i.source[0]
            const src = preview ? `/api/image?path=${encodeURIComponent(preview)}` : null
            return (
              <tr key={i.id} className="border-b border-surface-3/40 hover:bg-surface-2">
                <td className="p-2">
                  {src ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={src} alt="" className="w-7 h-7 rounded-full object-cover bg-surface-3" />
                  ) : (
                    <span className={`w-7 h-7 rounded-full flex items-center justify-center text-[8px] font-bold uppercase ${chipOf(i.pillar)}`}>{i.type.slice(0, 2)}</span>
                  )}
                </td>
                <td className="p-2">
                  <Link href={hrefOf(i)} className="font-mono text-zinc-200 hover:text-primary">{i.id}</Link>
                </td>
                <td className="p-2"><span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-semibold ${chipOf(i.pillar)}`}>{i.type}</span></td>
                <td className="p-2"><span className={`px-1 py-0.5 rounded text-[10px] ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span></td>
                <td className="p-2"><QualityBar score={i.quality} showLabel={false} /></td>
                <td className="p-2 text-zinc-500">{i.tags.slice(0, 3).join(', ')}{i.tags.length > 3 ? ` +${i.tags.length - 3}` : ''}</td>
                <td className="p-2">{i.relationships.length === 0 ? <span className="text-warning">⚠ 0</span> : i.relationships.length}</td>
                <td className="p-2 text-zinc-500">{i.updated || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
