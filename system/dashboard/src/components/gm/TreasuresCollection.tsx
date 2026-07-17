'use client'

// ponytail: clone of BestiaryCollection specialized to the treasures pillar (its
// types, guidance, owner/hook/lore-Q&A deltas). When the shared shell is lifted
// into one CollectionView, this folds in with the others.

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import type { ReviewItem } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import QualityBar from '@/components/widgets/QualityBar'
import VaultImage from '@/components/shared/VaultImage'
import { Tip } from './Tip'
import {
  Gem, Plus, Sparkles, ChevronDown, ChevronRight, Star, Loader2,
  Check, Flag, Archive, XCircle, ExternalLink, LayoutGrid, Table as TableIcon,
  Search,
} from 'lucide-react'

export type TreasureItem = ReviewItem & {
  origin: 'draft' | 'canon'
  owner: string | null
  hasHook: boolean
  signature: boolean
  question: boolean
  answer: boolean
  hasReveal: boolean
}

interface Toast { message: string; type: 'success' | 'error' }

const SELECT_CLS = 'text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors'
const TYPES = ['item', 'artifact', 'lore'] as const

// treasures.md Delta 2 build-guidance checklist (§6).
const GUIDANCE = [
  'Rewards that hook - the best treasure creates the next adventure',
  'Signature items / artifacts tied to factions or history',
  "History the party can discover - in ruins, NPC mouths, items",
  'Mysteries with answers - plant questions early, know the answers',
  'Consistent internal logic - magic, gods, money: pick rules, hold them',
]

const isLore = (i: TreasureItem) => i.type === 'lore'
const isItem = (i: TreasureItem) => !isLore(i) // item / artifact
// item with no owner and no relationship link (treasures.md Delta 6 amber chip)
const unowned = (i: TreasureItem) => isItem(i) && !i.owner && i.relationships.length === 0
const unanswered = (i: TreasureItem) => isLore(i) && i.question && !i.answer
const openMystery = (i: TreasureItem) => isLore(i) && i.question
// lore with no reveal channel - "wall of text" (Delta 4)
const wallOfText = (i: TreasureItem) => isLore(i) && !i.hasReveal

const chipCls = (type: string) =>
  type === 'lore' ? 'bg-teal-500/10 text-teal-400' : 'bg-orange-500/10 text-orange-400'

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

export default function TreasuresCollection({ items }: { items: TreasureItem[] }) {
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
  const [view, setView] = useState<'grid' | 'table'>('grid')
  const [sortBy, setSortBy] = useState('updated')
  const [needsReview, setNeedsReview] = useState(false)
  const [unownedOnly, setUnownedOnly] = useState(false)
  const [hookingOnly, setHookingOnly] = useState(false)
  const [sigOnly, setSigOnly] = useState(false)
  const [unansweredOnly, setUnansweredOnly] = useState(false)
  const [mysteryOnly, setMysteryOnly] = useState(false)

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const drafts = items.filter((i) => i.origin === 'draft').length
  const canon = items.filter((i) => i.origin === 'canon').length
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

  const q = search.trim().toLowerCase()
  const filtered = items
    .filter((i) => typeFilter === 'all' || i.type === typeFilter)
    .filter((i) => originFilter === 'all' || i.origin === originFilter)
    .filter((i) => statusFilter === 'all' || i.status === statusFilter)
    .filter((i) => !needsReview || (i.origin === 'draft' && !i.reviewed))
    .filter((i) => !unownedOnly || unowned(i))
    .filter((i) => !hookingOnly || (isItem(i) && i.hasHook))
    .filter((i) => !sigOnly || i.signature)
    .filter((i) => !unansweredOnly || unanswered(i))
    .filter((i) => !mysteryOnly || openMystery(i))
    .filter((i) =>
      !q ||
      i.id.toLowerCase().includes(q) ||
      i.excerpt.toLowerCase().includes(q) ||
      i.tags.some((t) => t.toLowerCase().includes(q))
    )
    .sort((a, b) => {
      // signature artifacts, then open unanswered mysteries, pin to the top
      if (a.signature !== b.signature) return a.signature ? -1 : 1
      if (unanswered(a) !== unanswered(b)) return unanswered(a) ? -1 : 1
      if (sortBy === 'quality') return b.quality - a.quality
      if (sortBy === 'name') return a.id.localeCompare(b.id)
      if (sortBy === 'status') return a.status.localeCompare(b.status)
      if (sortBy === 'links') return b.relationships.length - a.relationships.length
      // default: Type then Updated (Delta 7)
      if (a.type !== b.type) return a.type.localeCompare(b.type)
      return (b.updated ?? '').localeCompare(a.updated ?? '')
    })

  const cardHref = (i: TreasureItem) => `/gm/view/${i.uuid || encodeURIComponent(i.id)}`

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={Gem}
        title="Treasures & Lore"
        subtitle={`${items.length} entities · ${drafts} drafts · ${canon} canon`}
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
                    {(['item', 'artifact', 'lore'] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => create(t)}
                        className="w-full text-left px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-surface-3 rounded transition-colors capitalize"
                      >
                        {t === 'item' ? 'Item (loot / reward)' : t === 'artifact' ? 'Artifact (signature / historic)' : 'Lore (mystery / history)'}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
            <Tip label="Generate with AI - coming soon">
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
          Build guidance - the treasures &amp; lore checklist
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

        {/* Quick toggles (Delta 7) */}
        {([
          ['Needs review', needsReview, setNeedsReview],
          ['Unowned', unownedOnly, setUnownedOnly],
          ['Hooking', hookingOnly, setHookingOnly],
          ['Signature', sigOnly, setSigOnly],
          ['Unanswered', unansweredOnly, setUnansweredOnly],
          ['Open mystery', mysteryOnly, setMysteryOnly],
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
            <option value="updated">Type · Updated</option>
            <option value="quality">Quality</option>
            <option value="name">Name</option>
            <option value="status">Status</option>
            <option value="links">Most-linked</option>
          </select>
          <span className="text-xs text-zinc-600">{filtered.length} / {items.length}</span>
        </div>
      </div>

      {/* Collection */}
      {items.length === 0 ? (
        <div className="panel p-12 text-center">
          <Gem size={24} className="mx-auto text-zinc-600 mb-3" />
          <div className="text-zinc-400 text-sm">No treasures or lore yet</div>
          <div className="flex items-center justify-center gap-3 mt-3">
            <button onClick={() => create('item')} className="text-xs px-3 py-1.5 rounded bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-colors">+ New item</button>
            <Link href="/gm/inbox" className="text-xs text-zinc-500 hover:text-zinc-300">Drop sources in the Inbox →</Link>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="panel p-12 text-center text-zinc-500 text-sm">No entities match - clear filters</div>
      ) : view === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {filtered.map((i) => {
            const hoverBorder = isLore(i) ? 'hover:border-teal-500/30' : 'hover:border-orange-500/30'
            const hoverText = isLore(i) ? 'group-hover:text-teal-400' : 'group-hover:text-orange-400'
            return (
              <div key={i.id} className={`panel border border-surface-3 ${hoverBorder} transition-colors flex flex-col group overflow-hidden`}>
                <Link href={cardHref(i)} className="flex-1 p-3 flex gap-3">
                  <VaultImage path={i.tokenPath || i.source[0]} type={i.type} className="w-14 h-14 rounded-lg object-cover bg-surface-3 flex-shrink-0" alt="" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-xs font-mono text-zinc-100 truncate ${hoverText}`}>{i.id}</span>
                      {i.signature && <Star size={11} className="text-yellow-400 fill-yellow-400 flex-shrink-0" />}
                    </div>
                    {isItem(i) && i.owner ? (
                      <p className="text-[11px] text-zinc-500 truncate mt-0.5">wanted by {i.owner}</p>
                    ) : (
                      <p className="text-[11px] text-zinc-500 truncate mt-0.5">{i.excerpt || '-'}</p>
                    )}
                    <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase ${chipCls(i.type)}`}>{i.type}</span>
                      <span className={`text-[9px] px-1 py-0.5 rounded ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span>
                      <span className="text-[9px] font-mono text-zinc-500">Q{i.quality}</span>
                      {isItem(i) && i.hasHook && <span className="text-[9px] px-1 py-0.5 rounded bg-orange-500/15 text-orange-400" title="carries a hook - seeds the next adventure">→ hook</span>}
                      {isLore(i) && i.question && (
                        i.answer
                          ? <span className="text-[9px] px-1 py-0.5 rounded bg-success/10 text-success" title="mystery with an answer">answered</span>
                          : <span className="text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning" title="question with no answer">unanswered</span>
                      )}
                      {wallOfText(i) && <span className="text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning" title="no reveal channel - wall of text">wall of text</span>}
                      {unowned(i) && <span className="text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning" title="no owner and no quest link">unowned</span>}
                      {i.origin === 'draft' && !i.reviewed && <span className="text-[9px] px-1 py-0.5 rounded bg-warning/15 text-warning">new</span>}
                    </div>
                  </div>
                </Link>
                {/* Quick actions - drafts only (action endpoints operate on 01-Processing) */}
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
                <th className="p-2 font-medium">Image</th>
                <th className="p-2 font-medium">Type</th>
                <th className="p-2 font-medium">ID</th>
                <th className="p-2 font-medium">Owner / reveal</th>
                <th className="p-2 font-medium">Origin</th>
                <th className="p-2 font-medium w-28">Quality</th>
                <th className="p-2 font-medium">Status</th>
                <th className="p-2 font-medium">Tags</th>
                <th className="p-2 font-medium">Links</th>
                <th className="p-2 font-medium">Updated</th>
                <th className="p-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((i) => {
                return (
                <tr key={i.id} className="border-b border-surface-3/40 hover:bg-surface-2">
                  <td className="p-2">
                    <VaultImage path={i.tokenPath || i.source[0]} type={i.type} className="w-7 h-7 rounded-full object-cover bg-surface-3" alt="" />
                  </td>
                  <td className="p-2"><span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-semibold ${chipCls(i.type)}`}>{i.type}</span></td>
                  <td className="p-2">
                    <Link href={cardHref(i)} className="font-mono text-zinc-200 hover:text-orange-400 inline-flex items-center gap-1">
                      {i.id}
                      {i.signature && <Star size={10} className="text-yellow-400 fill-yellow-400" />}
                      {unanswered(i) && <span className="text-warning" title="unanswered mystery">?</span>}
                    </Link>
                  </td>
                  <td className="p-2 text-zinc-500">
                    {isItem(i)
                      ? (i.owner ?? (unowned(i) ? <span className="text-warning">⚠ unowned</span> : '-'))
                      : (i.hasReveal ? 'revealed' : <span className="text-warning">⚠ no reveal</span>)}
                  </td>
                  <td className="p-2"><span className={`px-1 py-0.5 rounded text-[10px] ${i.origin === 'canon' ? 'bg-success/10 text-success' : 'bg-surface-3 text-zinc-400'}`}>{i.origin}</span></td>
                  <td className="p-2"><QualityBar score={i.quality} showLabel={false} /></td>
                  <td className="p-2 text-zinc-400">{i.status}</td>
                  <td className="p-2 text-zinc-500">
                    {i.tags.slice(0, 3).join(', ')}{i.tags.length > 3 ? ` +${i.tags.length - 3}` : ''}
                  </td>
                  <td className="p-2">{i.relationships.length === 0 ? <span className="text-warning">⚠ 0</span> : i.relationships.length}</td>
                  <td className="p-2 text-zinc-500">{i.updated || '-'}</td>
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
              )})}
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
