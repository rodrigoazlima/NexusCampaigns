'use client'

// ponytail: clone of BestiaryCollection specialized to the factions pillar (its
// types, guidance, leader/stronghold/rival + clock deltas). When the shared shell
// (filter bar, grid/table, ActionBtn, toast) hits a fourth copy, lift it into one
// CollectionView. The clock is this page's signature widget (factions.md Delta 4).

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { ReviewItem } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import QualityBar from '@/components/widgets/QualityBar'
import { Tip } from './Tip'
import {
  Flag, Plus, Sparkles, ChevronDown, ChevronRight, ChevronLeft, Loader2,
  Check, Archive, XCircle, ExternalLink, LayoutGrid, Table as TableIcon, Clock,
  Search, Swords, User, Castle,
} from 'lucide-react'

export type FactionItem = ReviewItem & {
  origin: 'draft' | 'canon'
  leader: string | null
  stronghold: string | null
  rival: string | null
  clockSteps: string[]
  clockStep: number
}

interface Toast { message: string; type: 'success' | 'error' }

const TYPE_CHIP = 'bg-purple-500/10 text-purple-400'
const SELECT_CLS = 'text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors'
const TYPES = ['faction', 'organization', 'religion'] as const

// factions.md Delta 2 build-guidance checklist.
const GUIDANCE = [
  '2–4 factions with clashing goals (overlap → friction → plot)',
  'Each needs: goal · method · leader (NPC) · stronghold (location) · a resource',
  'A faction clock — what it does over coming weeks if uninterrupted',
  'Where the party fits — who courts them, who they threaten',
  'A religion / belief system if it matters',
]

function ActionBtn({
  label, variant = 'ghost', onClick, busy, disabled, children,
}: {
  label: string
  variant?: 'ghost' | 'success' | 'danger' | 'warning'
  onClick: () => void
  busy?: boolean
  disabled?: boolean
  children: React.ReactNode
}) {
  const variants: Record<string, string> = {
    ghost: 'border-surface-3 text-zinc-400 hover:text-zinc-100 hover:bg-surface-3',
    success: 'border-success/40 text-success hover:bg-success/20',
    danger: 'border-danger/40 text-danger hover:bg-danger/20',
    warning: 'border-warning/40 text-warning hover:bg-warning/20',
  }
  return (
    <Tip label={label}>
      <button
        onClick={onClick}
        disabled={busy || disabled}
        className={`w-8 h-8 flex items-center justify-center rounded-lg border transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${variants[variant]}`}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : children}
      </button>
    </Tip>
  )
}

// N-pip clock track; first `step` pips filled. No steps → amber "static" chip.
function ClockPips({ steps, step, size = 'sm' }: { steps: number; step: number; size?: 'sm' | 'lg' }) {
  if (steps === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning" title="no clock — won't act">
        static
      </span>
    )
  }
  const dot = size === 'lg' ? 'w-2.5 h-2.5' : 'w-1.5 h-1.5'
  return (
    <span className="inline-flex items-center gap-0.5" title={`clock ${step}/${steps}`}>
      {Array.from({ length: steps }).map((_, i) => (
        <span key={i} className={`${dot} rounded-full ${i < step ? 'bg-purple-400' : 'bg-surface-4'}`} />
      ))}
    </span>
  )
}

export default function FactionCollection({ items }: { items: FactionItem[] }) {
  const router = useRouter()
  const [toast, setToast] = useState<Toast | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)

  const [typeFilter, setTypeFilter] = useState('all')
  const [originFilter, setOriginFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [view, setView] = useState<'grid' | 'table' | 'board'>('grid')
  const [sortBy, setSortBy] = useState('updated')
  const [needsReview, setNeedsReview] = useState(false)
  const [orphans, setOrphans] = useState(false)
  const [noClock, setNoClock] = useState(false)
  const [leaderless, setLeaderless] = useState(false)
  const [noStronghold, setNoStronghold] = useState(false)
  const [atWar, setAtWar] = useState(false)

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const drafts = items.filter((i) => i.origin === 'draft').length
  const canon = items.filter((i) => i.origin === 'canon').length
  const withClocks = items.filter((i) => i.clockSteps.length > 0).length
  const leaderlessCount = items.filter((i) => !i.leader).length
  const statuses = Array.from(new Set(items.map((i) => i.status))).filter(Boolean).sort()

  const act = async (endpoint: string, filename: string, okMsg: string) => {
    setBusy(filename)
    try {
      const res = await fetch(`/api/gm/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      const data = await res.json()
      if (data.ok) { showToast(okMsg, 'success'); router.refresh() }
      else showToast(data.error ?? 'Action failed', 'error')
    } catch {
      showToast('Action failed', 'error')
    } finally {
      setBusy(null)
    }
  }

  // Advance/rewind the clock — persists clock_step to frontmatter (drafts only,
  // since /api/gm/edit operates on 01-Processing).
  const setClock = async (i: FactionItem, next: number) => {
    setBusy(i.filename)
    try {
      const res = await fetch('/api/gm/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: i.filename, fields: { clock_step: next } }),
      })
      const data = await res.json()
      if (data.ok) { showToast(`Clock → ${next}/${i.clockSteps.length}`, 'success'); router.refresh() }
      else showToast(data.error ?? 'Clock update failed', 'error')
    } catch {
      showToast('Clock update failed', 'error')
    } finally {
      setBusy(null)
    }
  }

  const create = async (type: (typeof TYPES)[number]) => {
    setNewOpen(false)
    setCreating(true)
    try {
      const res = await fetch('/api/gm/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type }),
      })
      const data = await res.json()
      if (data.ok) router.push(`/gm/view/${encodeURIComponent(data.id)}`)
      else showToast(data.error ?? 'Create failed', 'error')
    } catch {
      showToast('Create failed', 'error')
    } finally {
      setCreating(false)
    }
  }

  const q = search.trim().toLowerCase()
  const filtered = items
    .filter((i) => typeFilter === 'all' || i.type === typeFilter)
    .filter((i) => originFilter === 'all' || i.origin === originFilter)
    .filter((i) => statusFilter === 'all' || i.status === statusFilter)
    .filter((i) => !needsReview || (i.origin === 'draft' && !i.reviewed))
    .filter((i) => !orphans || i.relationships.length === 0)
    .filter((i) => !noClock || i.clockSteps.length === 0)
    .filter((i) => !leaderless || !i.leader)
    .filter((i) => !noStronghold || !i.stronghold)
    .filter((i) => !atWar || !!i.rival)
    .filter((i) =>
      !q ||
      i.id.toLowerCase().includes(q) ||
      i.excerpt.toLowerCase().includes(q) ||
      i.tags.some((t) => t.toLowerCase().includes(q))
    )
    .sort((a, b) => {
      if (sortBy === 'quality') return b.quality - a.quality
      if (sortBy === 'name') return a.id.localeCompare(b.id)
      if (sortBy === 'status') return a.status.localeCompare(b.status)
      if (sortBy === 'links') return b.relationships.length - a.relationships.length
      if (sortBy === 'clock') return b.clockStep - a.clockStep // clock progress
      return (b.updated ?? '').localeCompare(a.updated ?? '') // updated (default)
    })

  const tokenSrc = (i: FactionItem) =>
    i.tokenPath ? `/api/image?path=${encodeURIComponent(i.tokenPath)}` : null

  const cardHref = (i: FactionItem) =>
    i.origin === 'draft' ? `/gm/view/${encodeURIComponent(i.id)}` : '/library'

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={Flag}
        title="Factions & Powers"
        subtitle={`${items.length} entities · ${withClocks} with clocks · ${leaderlessCount} leaderless · ${drafts} drafts · ${canon} canon`}
        actions={
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                onClick={() => setNewOpen((v) => !v)}
                disabled={creating}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-colors disabled:opacity-50"
              >
                {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                New <ChevronDown size={12} />
              </button>
              {newOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setNewOpen(false)} />
                  <div className="absolute right-0 mt-1 z-50 w-52 panel p-1 shadow-xl">
                    {TYPES.map((t) => (
                      <button
                        key={t}
                        onClick={() => create(t)}
                        className="w-full text-left px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-surface-3 rounded transition-colors capitalize"
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
            <Tip label="Generate with AI — coming soon">
              <Link
                href="/gm/chat"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-surface-3 text-zinc-400 hover:text-zinc-200 border border-surface-3 transition-colors"
              >
                <Sparkles size={14} /> Generate with AI
              </Link>
            </Tip>
          </div>
        }
      />

      {/* Build guidance strip */}
      <div className="panel mb-4">
        <button
          onClick={() => setGuideOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-4 py-2.5 text-xs font-semibold text-zinc-300 hover:text-white transition-colors"
        >
          {guideOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Build guidance — the factions checklist
        </button>
        {guideOpen && (
          <ul className="px-4 pb-3 space-y-1.5 border-t border-surface-3/60 pt-3">
            {GUIDANCE.map((g) => (
              <li key={g} className="flex items-start gap-2 text-xs text-zinc-400">
                <span className="mt-0.5 w-3.5 h-3.5 rounded border border-surface-4 flex-shrink-0" />
                {g}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Filter bar */}
      <div className="panel p-3 mb-4 flex flex-wrap gap-2 items-center">
        <div className="relative">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-zinc-600" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search id, text, tags…"
            className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 pl-7 pr-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors w-48"
          />
        </div>

        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className={SELECT_CLS}>
          <option value="all">All Types</option>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <select value={originFilter} onChange={(e) => setOriginFilter(e.target.value)} className={SELECT_CLS}>
          <option value="all">All Origins</option>
          <option value="draft">draft</option>
          <option value="canon">canon</option>
        </select>

        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={SELECT_CLS}>
          <option value="all">All Statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* Quick toggles */}
        {([
          ['Needs review', needsReview, setNeedsReview],
          ['No clock', noClock, setNoClock],
          ['Leaderless', leaderless, setLeaderless],
          ['No stronghold', noStronghold, setNoStronghold],
          ['At war', atWar, setAtWar],
          ['Orphans', orphans, setOrphans],
        ] as const).map(([label, val, set]) => (
          <button
            key={label}
            onClick={() => set((v: boolean) => !v)}
            className={`text-xs px-2 py-1.5 rounded border transition-colors ${
              val ? 'border-primary/40 bg-primary/10 text-primary' : 'border-surface-3 text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {label}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded border border-surface-3 overflow-hidden">
            <button
              onClick={() => setView('grid')}
              className={`p-1.5 ${view === 'grid' ? 'bg-primary/15 text-primary' : 'text-zinc-500 hover:text-zinc-300'}`}
              aria-label="Grid view"
            ><LayoutGrid size={14} /></button>
            <button
              onClick={() => setView('table')}
              className={`p-1.5 ${view === 'table' ? 'bg-primary/15 text-primary' : 'text-zinc-500 hover:text-zinc-300'}`}
              aria-label="Table view"
            ><TableIcon size={14} /></button>
            <Tip label="Clocks board — advance several between sessions" side="bottom">
              <button
                onClick={() => setView('board')}
                className={`p-1.5 ${view === 'board' ? 'bg-primary/15 text-primary' : 'text-zinc-500 hover:text-zinc-300'}`}
                aria-label="Clocks board"
              ><Clock size={14} /></button>
            </Tip>
          </div>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className={SELECT_CLS}>
            <option value="updated">Updated</option>
            <option value="quality">Quality</option>
            <option value="name">Name</option>
            <option value="status">Status</option>
            <option value="links">Most-linked</option>
            <option value="clock">Clock progress</option>
          </select>
          <span className="text-xs text-zinc-600">{filtered.length} / {items.length}</span>
        </div>
      </div>

      {/* Collection */}
      {items.length === 0 ? (
        <div className="panel p-12 text-center">
          <Flag size={24} className="mx-auto text-zinc-600 mb-3" />
          <div className="text-zinc-400 text-sm">No factions yet</div>
          <div className="flex items-center justify-center gap-3 mt-3">
            <button onClick={() => create('faction')} className="text-xs px-3 py-1.5 rounded bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-colors">+ New faction</button>
            <Link href="/gm/inbox" className="text-xs text-zinc-500 hover:text-zinc-300">Drop sources in the Inbox →</Link>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="panel p-12 text-center text-zinc-500 text-sm">No entities match — clear filters</div>
      ) : view === 'board' ? (
        /* Clocks board — every faction's clock stacked as a horizontal track */
        <div className="panel divide-y divide-surface-3/40">
          {filtered.map((i) => {
            const steps = i.clockSteps.length
            const atMin = i.clockStep <= 0
            const atMax = i.clockStep >= steps
            return (
              <div key={i.id} className="flex items-center gap-3 px-4 py-3">
                <Link href={cardHref(i)} className="font-mono text-xs text-zinc-200 hover:text-purple-400 w-48 truncate">{i.id}</Link>
                {steps === 0 ? (
                  <span className="text-[11px] text-warning flex-1">static — no clock, won&apos;t act</span>
                ) : (
                  <>
                    <div className="flex items-center gap-1.5 flex-1 min-w-0">
                      {i.clockSteps.map((s, idx) => (
                        <Tip key={idx} label={s}>
                          <span className={`h-2 flex-1 min-w-2 rounded-full ${idx < i.clockStep ? 'bg-purple-400' : 'bg-surface-4'}`} />
                        </Tip>
                      ))}
                    </div>
                    <span className="text-[11px] font-mono text-zinc-500 w-10 text-right">{i.clockStep}/{steps}</span>
                    {i.origin === 'draft' ? (
                      <div className="flex items-center gap-1">
                        <ActionBtn label="Rewind clock" busy={busy === i.filename} disabled={atMin} onClick={() => setClock(i, i.clockStep - 1)}><ChevronLeft size={14} /></ActionBtn>
                        <ActionBtn label="Advance clock" busy={busy === i.filename} disabled={atMax} onClick={() => setClock(i, i.clockStep + 1)}><ChevronRight size={14} /></ActionBtn>
                      </div>
                    ) : (
                      <span className="text-[10px] text-zinc-600 w-[68px] text-center">canon</span>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      ) : view === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {filtered.map((i) => {
            const src = tokenSrc(i)
            const atMin = i.clockStep <= 0
            const atMax = i.clockStep >= i.clockSteps.length
            return (
              <div key={i.id} className="panel border border-surface-3 hover:border-purple-500/30 transition-colors flex flex-col group overflow-hidden">
                <Link href={cardHref(i)} className="flex-1 p-3 flex gap-3">
                  {src ? (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img src={src} alt="" className="w-14 h-14 rounded-lg object-cover bg-surface-3 flex-shrink-0" />
                  ) : (
                    <span className={`w-14 h-14 rounded-lg flex items-center justify-center text-xs font-bold uppercase flex-shrink-0 ${TYPE_CHIP}`}>{i.type.slice(0, 3)}</span>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-mono text-zinc-100 truncate group-hover:text-purple-400">{i.id}</span>
                    </div>
                    {/* leader · stronghold — amber when the faction→NPC/location link is missing */}
                    <div className="flex items-center gap-2 mt-1 text-[10px]">
                      {i.leader ? (
                        <span className="inline-flex items-center gap-1 text-zinc-400 truncate"><User size={9} className="flex-shrink-0" />{i.leader}</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-warning"><User size={9} /> leaderless</span>
                      )}
                      {i.stronghold ? (
                        <span className="inline-flex items-center gap-1 text-zinc-400 truncate"><Castle size={9} className="flex-shrink-0" />{i.stronghold}</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-warning"><Castle size={9} /> no seat</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase ${TYPE_CHIP}`}>{i.type}</span>
                      <span className={`text-[9px] px-1 py-0.5 rounded ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span>
                      <span className="text-[9px] font-mono text-zinc-500">Q{i.quality}</span>
                      <ClockPips steps={i.clockSteps.length} step={i.clockStep} />
                      {i.rival && <span className="inline-flex items-center gap-1 text-[9px] px-1 py-0.5 rounded bg-danger/10 text-danger" title={`at war with ${i.rival}`}><Swords size={9} /> war</span>}
                      {i.relationships.length === 0 && <span className="text-[9px] text-warning" title="orphan — no relationships">⚠</span>}
                      {i.origin === 'draft' && !i.reviewed && <span className="text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning">new</span>}
                    </div>
                  </div>
                </Link>
                {/* Quick actions — drafts only (action endpoints operate on 01-Processing) */}
                {i.origin === 'draft' && (
                  <div className="flex items-center gap-1.5 px-3 py-2 border-t border-surface-3/60 opacity-0 group-hover:opacity-100 transition-opacity">
                    {i.clockSteps.length > 0 && (
                      <>
                        <ActionBtn label="Rewind clock" busy={busy === i.filename} disabled={atMin} onClick={() => setClock(i, i.clockStep - 1)}><ChevronLeft size={14} /></ActionBtn>
                        <ActionBtn label="Advance clock" busy={busy === i.filename} disabled={atMax} onClick={() => setClock(i, i.clockStep + 1)}><ChevronRight size={14} /></ActionBtn>
                        <span className="w-px h-4 bg-surface-3" />
                      </>
                    )}
                    <ActionBtn label="Promote to canon" variant="success" busy={busy === i.filename} onClick={() => act('approve', i.filename, 'Promoted to Library')}><Check size={14} /></ActionBtn>
                    <ActionBtn label="Reject (quality → 1)" variant="danger" busy={busy === i.filename} onClick={() => act('reject', i.filename, 'Draft rejected')}><XCircle size={14} /></ActionBtn>
                    <ActionBtn label="Flag / reprocess" variant="warning" busy={busy === i.filename} onClick={() => act('flag', i.filename, 'Queued for reprocessing')}><Flag size={14} /></ActionBtn>
                    <ActionBtn label="Archive" busy={busy === i.filename} onClick={() => act('archive', i.filename, 'Archived')}><Archive size={14} /></ActionBtn>
                    <Link href={`/gm/view/${encodeURIComponent(i.id)}`} className="ml-auto"><Tip label="Open editor"><span className="w-8 h-8 flex items-center justify-center rounded-lg border border-surface-3 text-zinc-400 hover:text-zinc-100 hover:bg-surface-3 transition-colors"><ExternalLink size={14} /></span></Tip></Link>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        /* Table view */
        <div className="panel overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-zinc-500 border-b border-surface-3">
              <tr className="text-left">
                <th className="p-2 font-medium">Token</th>
                <th className="p-2 font-medium">ID</th>
                <th className="p-2 font-medium">Type</th>
                <th className="p-2 font-medium">Leader</th>
                <th className="p-2 font-medium">Stronghold</th>
                <th className="p-2 font-medium">Clock</th>
                <th className="p-2 font-medium">Origin</th>
                <th className="p-2 font-medium w-28">Quality</th>
                <th className="p-2 font-medium">Links</th>
                <th className="p-2 font-medium">Updated</th>
                <th className="p-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((i) => {
                const src = tokenSrc(i)
                const atMin = i.clockStep <= 0
                const atMax = i.clockStep >= i.clockSteps.length
                return (
                  <tr key={i.id} className="border-b border-surface-3/40 hover:bg-surface-2">
                    <td className="p-2">
                      {src ? (
                        /* eslint-disable-next-line @next/next/no-img-element */
                        <img src={src} alt="" className="w-7 h-7 rounded-full object-cover bg-surface-3" />
                      ) : (
                        <span className={`w-7 h-7 rounded-full flex items-center justify-center text-[8px] font-bold uppercase ${TYPE_CHIP}`}>{i.type.slice(0, 2)}</span>
                      )}
                    </td>
                    <td className="p-2">
                      <Link href={cardHref(i)} className="font-mono text-zinc-200 hover:text-purple-400 inline-flex items-center gap-1">
                        {i.id}
                        {i.rival && <Swords size={10} className="text-danger" />}
                      </Link>
                    </td>
                    <td className="p-2"><span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-semibold ${TYPE_CHIP}`}>{i.type}</span></td>
                    <td className="p-2">{i.leader ? <span className="text-zinc-400">{i.leader}</span> : <span className="text-warning">⚠ none</span>}</td>
                    <td className="p-2">{i.stronghold ? <span className="text-zinc-400">{i.stronghold}</span> : <span className="text-warning">⚠ none</span>}</td>
                    <td className="p-2"><ClockPips steps={i.clockSteps.length} step={i.clockStep} /></td>
                    <td className="p-2"><span className={`px-1 py-0.5 rounded text-[10px] ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span></td>
                    <td className="p-2"><QualityBar score={i.quality} showLabel={false} /></td>
                    <td className="p-2">{i.relationships.length === 0 ? <span className="text-warning">⚠ 0</span> : i.relationships.length}</td>
                    <td className="p-2 text-zinc-500">{i.updated || '—'}</td>
                    <td className="p-2">
                      <div className="flex items-center gap-1 justify-end">
                        {i.origin === 'draft' && (
                          <>
                            {i.clockSteps.length > 0 && (
                              <>
                                <ActionBtn label="Rewind clock" busy={busy === i.filename} disabled={atMin} onClick={() => setClock(i, i.clockStep - 1)}><ChevronLeft size={13} /></ActionBtn>
                                <ActionBtn label="Advance clock" busy={busy === i.filename} disabled={atMax} onClick={() => setClock(i, i.clockStep + 1)}><ChevronRight size={13} /></ActionBtn>
                              </>
                            )}
                            <ActionBtn label="Promote to canon" variant="success" busy={busy === i.filename} onClick={() => act('approve', i.filename, 'Promoted to Library')}><Check size={13} /></ActionBtn>
                            <ActionBtn label="Flag / reprocess" variant="warning" busy={busy === i.filename} onClick={() => act('flag', i.filename, 'Queued for reprocessing')}><Flag size={13} /></ActionBtn>
                            <ActionBtn label="Archive" busy={busy === i.filename} onClick={() => act('archive', i.filename, 'Archived')}><Archive size={13} /></ActionBtn>
                          </>
                        )}
                        <Link href={cardHref(i)}><Tip label="Open"><span className="w-8 h-8 flex items-center justify-center rounded-lg border border-surface-3 text-zinc-400 hover:text-zinc-100 hover:bg-surface-3 transition-colors"><ExternalLink size={13} /></span></Tip></Link>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {toast && (
        <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-lg text-sm font-medium z-50 shadow-lg ${toast.type === 'success' ? 'bg-success text-white' : 'bg-danger text-white'}`}>
          {toast.message}
        </div>
      )}
    </div>
  )
}
