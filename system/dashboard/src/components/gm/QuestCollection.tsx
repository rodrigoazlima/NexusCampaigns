'use client'

// ponytail: clone of FactionCollection specialized to the quests pillar (its
// types, guidance, shape/hook/clock/branches deltas). When the shared shell
// (filter bar, grid/table, ActionBtn, toast) hits a fourth copy, lift it into one
// CollectionView. Skipped Delta 5 (timeline-lane drag canvas) — add when the
// event/timeline redate API lands; grid + table cover the quest deltas now.

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { ReviewItem } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import QualityBar from '@/components/widgets/QualityBar'
import { Tip } from './Tip'
import {
  ScrollText, Plus, Sparkles, ChevronDown, ChevronRight, Loader2,
  Check, Flag, Archive, XCircle, ExternalLink, LayoutGrid, Table as TableIcon,
  Search, Star, Clock, User, MapPin, Gift, GitBranch, Briefcase, HelpCircle, Scale,
} from 'lucide-react'

export type QuestItem = ReviewItem & {
  origin: 'draft' | 'canon'
  shape: string | null
  openingHook: boolean
  patron: string | null
  place: string | null
  reward: string | null
  hasStakes: boolean
  deadline: string | null
  branches: number
}

interface Toast { message: string; type: 'success' | 'error' }

const TYPE_CHIP = 'bg-yellow-500/10 text-yellow-400'
const SELECT_CLS = 'text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors'
const TYPES = ['quest', 'event', 'timeline'] as const
const SHAPES = ['job', 'mystery', 'moral'] as const

const SHAPE_ICON: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  job: Briefcase, mystery: HelpCircle, moral: Scale,
}

// quests.md Delta 2 build-guidance checklist.
const GUIDANCE = [
  'An opening hook dropping the party into trouble in the first 15 min',
  '3+ quest threads of different shapes: a clear job · a mystery · a moral choice',
  'Stakes the party cares about (the innkeeper, not "the world")',
  'A ticking clock — a deadline / advancing threat',
  'Branches, not rails — ≥2 ways each quest can go',
  'A campaign timeline of events that happen regardless of the party',
]

function ActionBtn({
  label, variant = 'ghost', onClick, busy, children,
}: {
  label: string
  variant?: 'ghost' | 'success' | 'danger' | 'warning'
  onClick: () => void
  busy?: boolean
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
        disabled={busy}
        className={`w-8 h-8 flex items-center justify-center rounded-lg border transition-colors disabled:opacity-40 ${variants[variant]}`}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : children}
      </button>
    </Tip>
  )
}

// Small shape badge (job/mystery/moral). Null shape → amber "no shape" hint.
function ShapeChip({ shape }: { shape: string | null }) {
  if (!shape) return <span className="text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning" title="no shape — job/mystery/moral">no shape</span>
  const Icon = SHAPE_ICON[shape]
  return (
    <span className={`inline-flex items-center gap-1 text-[9px] px-1 py-0.5 rounded font-semibold uppercase ${TYPE_CHIP}`}>
      {Icon && <Icon size={9} />}{shape}
    </span>
  )
}

export default function QuestCollection({ items }: { items: QuestItem[] }) {
  const router = useRouter()
  const [toast, setToast] = useState<Toast | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)

  const [typeFilter, setTypeFilter] = useState('all')
  const [shapeFilter, setShapeFilter] = useState('all')
  const [originFilter, setOriginFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [view, setView] = useState<'grid' | 'table'>('grid')
  const [sortBy, setSortBy] = useState('updated')
  const [needsReview, setNeedsReview] = useState(false)
  const [orphans, setOrphans] = useState(false)
  const [hookOnly, setHookOnly] = useState(false)
  const [noClock, setNoClock] = useState(false)
  const [rail, setRail] = useState(false)
  const [unstaked, setUnstaked] = useState(false)

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const quests = items.filter((i) => i.type === 'quest')
  const drafts = items.filter((i) => i.origin === 'draft').length
  const canon = items.filter((i) => i.origin === 'canon').length
  const hasHook = quests.some((i) => i.openingHook)
  const withClock = quests.filter((i) => i.deadline).length
  const statuses = Array.from(new Set(items.map((i) => i.status))).filter(Boolean).sort()

  // Delta 2 rollup — which shapes are present among quests (— for a missing one).
  const shapeRollup = SHAPES.map((s) => (quests.some((i) => i.shape === s) ? s : '—')).join('/')

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
      if (data.ok) router.push(`/gm/view/${data.uuid || encodeURIComponent(data.id)}`)
      else showToast(data.error ?? 'Create failed', 'error')
    } catch {
      showToast('Create failed', 'error')
    } finally {
      setCreating(false)
    }
  }

  // rail/unstaked/clock checks only bite quests (events/timelines lack branches).
  const q = search.trim().toLowerCase()
  const filtered = items
    .filter((i) => typeFilter === 'all' || i.type === typeFilter)
    .filter((i) => shapeFilter === 'all' || i.shape === shapeFilter)
    .filter((i) => originFilter === 'all' || i.origin === originFilter)
    .filter((i) => statusFilter === 'all' || i.status === statusFilter)
    .filter((i) => !needsReview || (i.origin === 'draft' && !i.reviewed))
    .filter((i) => !orphans || i.relationships.length === 0)
    .filter((i) => !hookOnly || i.openingHook)
    .filter((i) => !noClock || (i.type === 'quest' && !i.deadline))
    .filter((i) => !rail || (i.type === 'quest' && i.branches < 2))
    .filter((i) => !unstaked || (i.type === 'quest' && !i.hasStakes))
    .filter((i) =>
      !q ||
      i.id.toLowerCase().includes(q) ||
      i.excerpt.toLowerCase().includes(q) ||
      i.tags.some((t) => t.toLowerCase().includes(q))
    )
    .sort((a, b) => {
      // Opening hook always pins to the top — the campaign's starting point.
      if (a.openingHook !== b.openingHook) return a.openingHook ? -1 : 1
      if (sortBy === 'quality') return b.quality - a.quality
      if (sortBy === 'name') return a.id.localeCompare(b.id)
      if (sortBy === 'status') return a.status.localeCompare(b.status)
      if (sortBy === 'links') return b.relationships.length - a.relationships.length
      if (sortBy === 'deadline') return (a.deadline ? 0 : 1) - (b.deadline ? 0 : 1) || (a.deadline ?? '').localeCompare(b.deadline ?? '')
      return (b.updated ?? '').localeCompare(a.updated ?? '') // updated (default)
    })

  const tokenSrc = (i: QuestItem) => {
    const path = i.tokenPath || i.source[0]
    return path ? `/api/image?path=${encodeURIComponent(path)}` : null
  }

  const cardHref = (i: QuestItem) => `/gm/view/${i.uuid || encodeURIComponent(i.id)}`

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={ScrollText}
        title="Quests & Story"
        subtitle={`${items.length} entities · hook ${hasHook ? '✓' : '—'} · threads ${shapeRollup} · ${withClock} clocks · ${drafts} drafts · ${canon} canon`}
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
          Build guidance — the story checklist
          <span className="ml-auto font-normal text-zinc-500">hook {hasHook ? '✓' : '—'} · threads {shapeRollup} · {withClock} clock</span>
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

        <select value={shapeFilter} onChange={(e) => setShapeFilter(e.target.value)} className={SELECT_CLS}>
          <option value="all">All Shapes</option>
          {SHAPES.map((s) => <option key={s} value={s}>{s}</option>)}
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
          ['Opening hook', hookOnly, setHookOnly],
          ['No clock', noClock, setNoClock],
          ['Rail', rail, setRail],
          ['Unstaked', unstaked, setUnstaked],
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
          </div>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className={SELECT_CLS}>
            <option value="updated">Updated</option>
            <option value="quality">Quality</option>
            <option value="name">Name</option>
            <option value="status">Status</option>
            <option value="links">Most-linked</option>
            <option value="deadline">Deadline</option>
          </select>
          <span className="text-xs text-zinc-600">{filtered.length} / {items.length}</span>
        </div>
      </div>

      {/* Collection */}
      {items.length === 0 ? (
        <div className="panel p-12 text-center">
          <ScrollText size={24} className="mx-auto text-zinc-600 mb-3" />
          <div className="text-zinc-400 text-sm">No quests yet</div>
          <div className="flex items-center justify-center gap-3 mt-3">
            <button onClick={() => create('quest')} className="text-xs px-3 py-1.5 rounded bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-colors">+ New quest</button>
            <Link href="/gm/inbox" className="text-xs text-zinc-500 hover:text-zinc-300">Drop sources in the Inbox →</Link>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="panel p-12 text-center text-zinc-500 text-sm">No entities match — clear filters</div>
      ) : view === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {filtered.map((i) => {
            const src = tokenSrc(i)
            const isQuest = i.type === 'quest'
            return (
              <div key={i.id} className="panel border border-surface-3 hover:border-yellow-500/30 transition-colors flex flex-col group overflow-hidden">
                <Link href={cardHref(i)} className="flex-1 p-3 flex gap-3">
                  {src ? (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img src={src} alt="" className="w-14 h-14 rounded-lg object-cover bg-surface-3 flex-shrink-0" />
                  ) : (
                    <span className={`w-14 h-14 rounded-lg flex items-center justify-center text-xs font-bold uppercase flex-shrink-0 ${TYPE_CHIP}`}>{i.type.slice(0, 3)}</span>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      {i.openingHook && <Star size={11} className="text-yellow-400 flex-shrink-0" />}
                      <span className="text-xs font-mono text-zinc-100 truncate group-hover:text-yellow-400">{i.id}</span>
                    </div>
                    {/* patron · place — amber when the quest→NPC/location link is missing */}
                    {isQuest && (
                      <div className="flex items-center gap-2 mt-1 text-[10px]">
                        {i.patron ? (
                          <span className="inline-flex items-center gap-1 text-zinc-400 truncate"><User size={9} className="flex-shrink-0" />{i.patron}</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-warning"><User size={9} /> no patron</span>
                        )}
                        {i.place ? (
                          <span className="inline-flex items-center gap-1 text-zinc-400 truncate"><MapPin size={9} className="flex-shrink-0" />{i.place}</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-warning"><MapPin size={9} /> no place</span>
                        )}
                      </div>
                    )}
                    <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                      {isQuest ? (
                        <ShapeChip shape={i.shape} />
                      ) : (
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase ${TYPE_CHIP}`}>{i.type}</span>
                      )}
                      <span className={`text-[9px] px-1 py-0.5 rounded ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span>
                      <span className="text-[9px] font-mono text-zinc-500">Q{i.quality}</span>
                      {isQuest && (i.deadline
                        ? <span className="inline-flex items-center gap-1 text-[9px] px-1 py-0.5 rounded bg-yellow-500/10 text-yellow-400" title={`deadline: ${i.deadline}`}><Clock size={9} /> clock</span>
                        : <span className="inline-flex items-center gap-1 text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning" title="no clock — a chore, not urgent"><Clock size={9} /> no clock</span>
                      )}
                      {isQuest && i.branches < 2 && <span className="inline-flex items-center gap-1 text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning" title="rail — single path, no branches"><GitBranch size={9} /> rail</span>}
                      {i.reward && <span className="inline-flex items-center gap-1 text-[9px] text-zinc-500 truncate" title={`reward: ${i.reward}`}><Gift size={9} />{i.reward}</span>}
                      {i.relationships.length === 0 && <span className="text-[9px] text-warning" title="orphan — no relationships">⚠</span>}
                      {i.origin === 'draft' && !i.reviewed && <span className="text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning">new</span>}
                    </div>
                  </div>
                </Link>
                {/* Quick actions — drafts only (action endpoints operate on 01-Processing) */}
                {i.origin === 'draft' && (
                  <div className="flex items-center gap-1.5 px-3 py-2 border-t border-surface-3/60 opacity-0 group-hover:opacity-100 transition-opacity">
                    <ActionBtn label="Promote to canon" variant="success" busy={busy === i.filename} onClick={() => act('approve', i.filename, 'Promoted to Library')}><Check size={14} /></ActionBtn>
                    <ActionBtn label="Reject (quality → 1)" variant="danger" busy={busy === i.filename} onClick={() => act('reject', i.filename, 'Draft rejected')}><XCircle size={14} /></ActionBtn>
                    <ActionBtn label="Flag / reprocess" variant="warning" busy={busy === i.filename} onClick={() => act('flag', i.filename, 'Queued for reprocessing')}><Flag size={14} /></ActionBtn>
                    <ActionBtn label="Archive" busy={busy === i.filename} onClick={() => act('archive', i.filename, 'Archived')}><Archive size={14} /></ActionBtn>
                    <Link href={`/gm/view/${i.uuid || encodeURIComponent(i.id)}`} className="ml-auto"><Tip label="Open editor"><span className="w-8 h-8 flex items-center justify-center rounded-lg border border-surface-3 text-zinc-400 hover:text-zinc-100 hover:bg-surface-3 transition-colors"><ExternalLink size={14} /></span></Tip></Link>
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
                <th className="p-2 font-medium">Type</th>
                <th className="p-2 font-medium">ID</th>
                <th className="p-2 font-medium">Shape</th>
                <th className="p-2 font-medium">Patron</th>
                <th className="p-2 font-medium">Place</th>
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
                const isQuest = i.type === 'quest'
                return (
                  <tr key={i.id} className="border-b border-surface-3/40 hover:bg-surface-2">
                    <td className="p-2"><span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-semibold ${TYPE_CHIP}`}>{i.type}</span></td>
                    <td className="p-2">
                      <Link href={cardHref(i)} className="font-mono text-zinc-200 hover:text-yellow-400 inline-flex items-center gap-1">
                        {i.openingHook && <Star size={10} className="text-yellow-400" />}
                        {i.id}
                        {isQuest && i.branches < 2 && <GitBranch size={10} className="text-warning" />}
                      </Link>
                    </td>
                    <td className="p-2">{isQuest ? <ShapeChip shape={i.shape} /> : <span className="text-zinc-600">—</span>}</td>
                    <td className="p-2">{!isQuest ? <span className="text-zinc-600">—</span> : i.patron ? <span className="text-zinc-400">{i.patron}</span> : <span className="text-warning">⚠ none</span>}</td>
                    <td className="p-2">{!isQuest ? <span className="text-zinc-600">—</span> : i.place ? <span className="text-zinc-400">{i.place}</span> : <span className="text-warning">⚠ none</span>}</td>
                    <td className="p-2">{!isQuest ? <span className="text-zinc-600">—</span> : i.deadline ? <span className="inline-flex items-center gap-1 text-yellow-400"><Clock size={11} />{i.deadline}</span> : <span className="text-warning">⚠ none</span>}</td>
                    <td className="p-2"><span className={`px-1 py-0.5 rounded text-[10px] ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span></td>
                    <td className="p-2"><QualityBar score={i.quality} showLabel={false} /></td>
                    <td className="p-2">{i.relationships.length === 0 ? <span className="text-warning">⚠ 0</span> : i.relationships.length}</td>
                    <td className="p-2 text-zinc-500">{i.updated || '—'}</td>
                    <td className="p-2">
                      <div className="flex items-center gap-1 justify-end">
                        {i.origin === 'draft' && (
                          <>
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
