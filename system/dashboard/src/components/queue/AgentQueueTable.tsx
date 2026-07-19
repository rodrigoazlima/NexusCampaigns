'use client'

import { useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Search, ArrowUp, ArrowDown, Pause, Play, RotateCcw, Trash2, Loader2,
  ChevronLeft, ChevronRight,
} from 'lucide-react'
import QueueThumb from './QueueThumb'
import { formatRelative } from '@/lib/utils'
import type { QueueItem } from '@/lib/types'

type AgentStatus = 'pending' | 'stuck' | 'paused' | 'done' | 'error' | 'skip'
type SortKey = 'path' | 'type' | 'ingestedAt' | 'updatedAt'

const STATUS_ORDER: AgentStatus[] = ['error', 'stuck', 'pending', 'paused', 'done', 'skip']

const STATUS_META: Record<AgentStatus, { label: string; badge: string; chip: string }> = {
  error:   { label: 'Error',   badge: 'bg-danger/15 text-danger border-danger/40',   chip: 'bg-danger/15 text-danger border-danger/40' },
  stuck:   { label: 'Stuck',   badge: 'bg-danger/15 text-danger border-danger/40',   chip: 'bg-danger/15 text-danger border-danger/40' },
  pending: { label: 'Pending', badge: 'bg-warning/15 text-warning border-warning/40', chip: 'bg-warning/15 text-warning border-warning/40' },
  paused:  { label: 'Paused',  badge: 'bg-neutral/15 text-neutral border-neutral/40', chip: 'bg-neutral/15 text-neutral border-neutral/40' },
  done:    { label: 'Done',    badge: 'bg-success/15 text-success border-success/40', chip: 'bg-success/15 text-success border-success/40' },
  skip:    { label: 'Skip',    badge: 'bg-surface-3 text-zinc-500 border-surface-3',  chip: 'bg-surface-3 text-zinc-500 border-surface-3' },
}

const PAGE_SIZES = [25, 50, 100]
const filename = (p: string) => p.split('/').pop() ?? p

function resolveAgentStatus(item: QueueItem, agent: string): AgentStatus {
  const s = item.agents[agent] as AgentStatus | undefined
  if (s === 'pending') {
    const cutoff = Date.now() - 24 * 60 * 60 * 1000
    const t = new Date(item.ingestedAt).getTime()
    if (!isNaN(t) && t < cutoff) return 'stuck'
  }
  return s ?? 'skip'
}

function SortHeader({ label, active, dir, onClick }: { label: string; active: boolean; dir: 'asc' | 'desc'; onClick: () => void }) {
  return (
    <th className="px-4 py-2 text-left cursor-pointer select-none hover:text-zinc-300" onClick={onClick}>
      <span className="inline-flex items-center gap-1">
        {label}
        {active && (dir === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
      </span>
    </th>
  )
}

interface Props {
  items: QueueItem[]
  agent: string
  byType: Record<string, number>
}

export default function AgentQueueTable({ items, agent, byType }: Props) {
  const router = useRouter()
  const [search, setSearch] = useState('')
  const [types, setTypes] = useState<Set<string>>(new Set())
  const [statuses, setStatuses] = useState<Set<AgentStatus>>(new Set())
  const [sortKey, setSortKey] = useState<SortKey>('ingestedAt')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const confirmTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const toggleType = (t: string) => setTypes((prev) => {
    const next = new Set(prev)
    if (next.has(t)) next.delete(t); else next.add(t)
    return next
  })
  const toggleStatus = (s: AgentStatus) => setStatuses((prev) => {
    const next = new Set(prev)
    if (next.has(s)) next.delete(s); else next.add(s)
    return next
  })

  const searched = useMemo(() => {
    const q = search.trim().toLowerCase()
    return items
      .filter((i) => types.size === 0 || types.has(i.type))
      .filter((i) => !q || filename(i.path).toLowerCase().includes(q))
  }, [items, search, types])

  const statusCounts = useMemo(() => {
    const counts: Record<AgentStatus, number> = { error: 0, stuck: 0, pending: 0, paused: 0, done: 0, skip: 0 }
    for (const item of searched) counts[resolveAgentStatus(item, agent)]++
    return counts
  }, [searched, agent])

  const visible = useMemo(() => {
    if (statuses.size === 0) return searched
    return searched.filter((i) => statuses.has(resolveAgentStatus(i, agent)))
  }, [searched, statuses, agent])

  const sorted = useMemo(() => {
    const copy = [...visible]
    copy.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'ingestedAt') cmp = new Date(a.ingestedAt).getTime() - new Date(b.ingestedAt).getTime()
      else if (sortKey === 'updatedAt') cmp = new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime()
      else if (sortKey === 'type') cmp = a.type.localeCompare(b.type)
      else cmp = filename(a.path).localeCompare(filename(b.path))
      return sortDir === 'asc' ? cmp : -cmp
    })
    return copy
  }, [visible, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const clampedPage = Math.min(page, totalPages)
  const pageItems = useMemo(
    () => sorted.slice((clampedPage - 1) * pageSize, clampedPage * pageSize),
    [sorted, clampedPage, pageSize],
  )

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir(key === 'ingestedAt' ? 'desc' : 'asc') }
  }

  const pageAllSelected = pageItems.length > 0 && pageItems.every((i) => selected.has(i.path))
  const toggleSelectAllOnPage = () => setSelected((prev) => {
    const next = new Set(prev)
    if (pageAllSelected) pageItems.forEach((i) => next.delete(i.path))
    else pageItems.forEach((i) => next.add(i.path))
    return next
  })
  const toggleSelect = (p: string) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(p)) next.delete(p); else next.add(p)
    return next
  })

  const armConfirm = (key: string) => {
    setConfirming((prev) => new Set(prev).add(key))
    const existing = confirmTimers.current.get(key)
    if (existing) clearTimeout(existing)
    confirmTimers.current.set(key, setTimeout(() => {
      setConfirming((prev) => { const next = new Set(prev); next.delete(key); return next })
      confirmTimers.current.delete(key)
    }, 4000))
  }
  const disarmConfirm = (key: string) => {
    const existing = confirmTimers.current.get(key)
    if (existing) { clearTimeout(existing); confirmTimers.current.delete(key) }
    setConfirming((prev) => { const next = new Set(prev); next.delete(key); return next })
  }

  const run = async (paths: string[], fn: () => Promise<void>) => {
    setBusy((prev) => new Set([...prev, ...paths]))
    try {
      await fn()
      setSelected((prev) => { const next = new Set(prev); paths.forEach((p) => next.delete(p)); return next })
      router.refresh()
    } finally {
      setBusy((prev) => { const next = new Set(prev); paths.forEach((p) => next.delete(p)); return next })
    }
  }

  const pauseAgent = (paths: string[]) => run(paths, async () => {
    await fetch('/api/queue/pause', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths, agent }),
    })
  })
  const resumeAgent = (paths: string[]) => run(paths, async () => {
    await fetch('/api/queue/resume', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths, agent }),
    })
  })
  const reprocessAgent = (paths: string[]) => run(paths, async () => {
    await Promise.all(paths.map((path) => fetch('/api/gm/queue/reprocess', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, agent }),
    })))
  })
  const deleteItems = (paths: string[]) => {
    paths.forEach(disarmConfirm)
    return run(paths, async () => {
      await fetch('/api/queue/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths }),
      })
    })
  }
  const handleDeleteClick = (key: string, paths: string[]) => {
    if (confirming.has(key)) deleteItems(paths)
    else armConfirm(key)
  }

  const selectedItems = items.filter((i) => selected.has(i.path))
  const selectedCanPause = selectedItems.some((i) => resolveAgentStatus(i, agent) === 'pending' || resolveAgentStatus(i, agent) === 'stuck')
  const selectedCanResume = selectedItems.some((i) => resolveAgentStatus(i, agent) === 'paused')

  const renderActions = (item: QueueItem, status: AgentStatus, size: 'sm' | 'lg') => {
    const btnSize = size === 'lg' ? 'w-8 h-8' : 'w-6 h-6'
    const iconSize = size === 'lg' ? 14 : 12
    return (
      <div className="flex items-center gap-1">
        {(status === 'pending' || status === 'stuck') && (
          <button
            type="button"
            title="Pause processing for this item"
            onClick={() => pauseAgent([item.path])}
            disabled={busy.has(item.path)}
            className={`flex items-center justify-center ${btnSize} rounded text-zinc-500 hover:text-warning hover:bg-warning/10 transition-colors disabled:opacity-50`}
          >
            {busy.has(item.path) ? <Loader2 size={iconSize} className="animate-spin" /> : <Pause size={iconSize} />}
          </button>
        )}
        {status === 'paused' && (
          <button
            type="button"
            title="Continue processing for this item"
            onClick={() => resumeAgent([item.path])}
            disabled={busy.has(item.path)}
            className={`flex items-center justify-center ${btnSize} rounded text-zinc-500 hover:text-neutral hover:bg-neutral/10 transition-colors disabled:opacity-50`}
          >
            {busy.has(item.path) ? <Loader2 size={iconSize} className="animate-spin" /> : <Play size={iconSize} />}
          </button>
        )}
        {status !== 'skip' && (
          <button
            type="button"
            title="Force this item to reprocess"
            onClick={() => reprocessAgent([item.path])}
            disabled={busy.has(item.path)}
            className={`flex items-center justify-center ${btnSize} rounded text-zinc-500 hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-50`}
          >
            {busy.has(item.path) ? <Loader2 size={iconSize} className="animate-spin" /> : <RotateCcw size={iconSize} />}
          </button>
        )}
        <button
          type="button"
          title={confirming.has(item.path) ? 'Click again to permanently delete' : 'Delete this item - source, generated token, and thumbnail'}
          onClick={() => handleDeleteClick(item.path, [item.path])}
          disabled={busy.has(item.path)}
          className={`flex items-center justify-center h-6 px-1.5 rounded transition-colors disabled:opacity-50 ${size === 'lg' ? 'h-8' : 'h-6'} ${
            confirming.has(item.path) ? 'text-danger bg-danger/15 border border-danger/40' : 'text-zinc-500 hover:text-danger hover:bg-danger/10'
          }`}
        >
          {busy.has(item.path) ? <Loader2 size={iconSize} className="animate-spin" /> : <Trash2 size={iconSize} />}
          {confirming.has(item.path) && <span className="ml-1 text-[11px] font-semibold whitespace-nowrap">Confirm?</span>}
        </button>
      </div>
    )
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative w-full sm:w-56">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-zinc-600" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by filename…"
            className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 pl-7 pr-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors w-full"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {Object.entries(byType).map(([type, count]) => (
            <button
              key={type}
              type="button"
              onClick={() => toggleType(type)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                types.has(type) ? 'bg-primary/15 text-primary border-primary/40' : 'bg-surface-2 text-zinc-400 border-surface-3 hover:text-zinc-200'
              }`}
            >
              {type} <span className="text-zinc-600">{count}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {STATUS_ORDER.filter((s) => statusCounts[s] > 0 || statuses.has(s)).map((status) => (
            <button
              key={status}
              type="button"
              onClick={() => toggleStatus(status)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                statuses.has(status) ? STATUS_META[status].chip : 'bg-surface-2 text-zinc-400 border-surface-3 hover:text-zinc-200'
              }`}
            >
              {STATUS_META[status].label} <span className="text-zinc-600">{statusCounts[status]}</span>
            </button>
          ))}
        </div>
        {(search || types.size > 0 || statuses.size > 0) && (
          <span className="text-xs text-zinc-600">{sorted.length} / {items.length}</span>
        )}
      </div>

      <div className="panel overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 min-h-[45px]">
          <span className="text-sm font-semibold text-zinc-200">Items ({items.length})</span>
          {selected.size > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              {selectedCanPause && (
                <button
                  type="button"
                  onClick={() => pauseAgent([...selected])}
                  disabled={[...selected].some((p) => busy.has(p))}
                  title="Pause processing for the selected items"
                  className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 transition-colors disabled:opacity-50"
                >
                  <Pause size={11} /> Pause {selected.size}
                </button>
              )}
              {selectedCanResume && (
                <button
                  type="button"
                  onClick={() => resumeAgent([...selected])}
                  disabled={[...selected].some((p) => busy.has(p))}
                  title="Continue processing for the selected items"
                  className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-neutral/10 text-neutral border border-neutral/30 hover:bg-neutral/20 transition-colors disabled:opacity-50"
                >
                  <Play size={11} /> Continue {selected.size}
                </button>
              )}
              <button
                type="button"
                onClick={() => reprocessAgent([...selected])}
                disabled={[...selected].some((p) => busy.has(p))}
                title="Force reprocessing for the selected items"
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors disabled:opacity-50"
              >
                <RotateCcw size={11} /> Reprocess {selected.size}
              </button>
              <button
                type="button"
                onClick={() => handleDeleteClick('bulk', [...selected])}
                disabled={[...selected].some((p) => busy.has(p))}
                title="Delete the selected items - source, generated token, and thumbnail"
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-danger/10 text-danger border border-danger/30 hover:bg-danger/20 transition-colors disabled:opacity-50"
              >
                <Trash2 size={11} /> {confirming.has('bulk') ? `Confirm delete ${selected.size}?` : `Delete ${selected.size}`}
              </button>
            </div>
          )}
        </div>

        {sorted.length === 0 ? (
          <div className="p-6 text-center text-zinc-500 text-sm">No items match the current filters</div>
        ) : (
          <>
            {/* Desktop/tablet: full table */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-surface-3 text-zinc-500">
                    <th className="px-4 py-2 text-left">
                      <input type="checkbox" checked={pageAllSelected} onChange={toggleSelectAllOnPage} className="cursor-pointer" />
                    </th>
                    <th className="px-4 py-2 text-left"></th>
                    <SortHeader label="File" active={sortKey === 'path'} dir={sortDir} onClick={() => toggleSort('path')} />
                    <SortHeader label="Ingested" active={sortKey === 'ingestedAt'} dir={sortDir} onClick={() => toggleSort('ingestedAt')} />
                    <SortHeader label="Updated" active={sortKey === 'updatedAt'} dir={sortDir} onClick={() => toggleSort('updatedAt')} />
                    <th className="px-4 py-2 text-right">Reruns</th>
                    <th className="px-4 py-2 text-left">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((item) => {
                    const status = resolveAgentStatus(item, agent)
                    const meta = STATUS_META[status]
                    const reruns = item.reruns[agent] ?? 0
                    return (
                      <tr key={item.path} className="border-b border-surface-3/50 hover:bg-surface-2">
                        <td className="px-4 py-2">
                          <input
                            type="checkbox"
                            checked={selected.has(item.path)}
                            onChange={() => toggleSelect(item.path)}
                            className="cursor-pointer"
                          />
                        </td>
                        <td className="px-4 py-2"><QueueThumb path={item.path} /></td>
                        <td className="px-4 py-2">
                          <div className="font-mono text-zinc-300">{filename(item.path)}</div>
                          <div className="flex items-center gap-1.5 mt-1">
                            <span className={`text-[9px] px-1.5 py-0.5 rounded-full border font-medium ${meta.badge}`}>{meta.label}</span>
                            <span className="text-zinc-600">{item.type}</span>
                          </div>
                        </td>
                        <td className="px-4 py-2 text-zinc-400">{formatRelative(item.ingestedAt)}</td>
                        <td className="px-4 py-2 text-zinc-400">{formatRelative(item.updatedAt)}</td>
                        <td className="px-4 py-2 text-right text-zinc-500 font-mono">{reruns || '-'}</td>
                        <td className="px-4 py-2">{renderActions(item, status, 'sm')}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile: card list - a 7-column table doesn't fit a phone screen */}
            <div className="md:hidden divide-y divide-surface-3/50">
              {pageItems.map((item) => {
                const status = resolveAgentStatus(item, agent)
                const meta = STATUS_META[status]
                const reruns = item.reruns[agent] ?? 0
                return (
                  <div key={item.path} className="p-3 flex gap-3">
                    <input
                      type="checkbox"
                      checked={selected.has(item.path)}
                      onChange={() => toggleSelect(item.path)}
                      className="cursor-pointer mt-1 shrink-0 w-4 h-4"
                    />
                    <div className="shrink-0"><QueueThumb path={item.path} /></div>
                    <div className="min-w-0 flex-1">
                      <div className="font-mono text-zinc-300 text-xs break-all">{filename(item.path)}</div>
                      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                        <span className={`text-[9px] px-1.5 py-0.5 rounded-full border font-medium ${meta.badge}`}>{meta.label}</span>
                        <span className="text-zinc-600 text-xs">{item.type}</span>
                        {reruns > 0 && <span className="text-zinc-500 text-xs font-mono">· {reruns} reruns</span>}
                      </div>
                      <div className="flex items-center gap-2.5 mt-1 text-[10px] text-zinc-500">
                        <span>In {formatRelative(item.ingestedAt)}</span>
                        <span>Upd {formatRelative(item.updatedAt)}</span>
                      </div>
                      <div className="mt-2">{renderActions(item, status, 'lg')}</div>
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="px-4 py-2.5 border-t border-surface-3 flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-500">
              <div className="flex items-center gap-2">
                <span>Rows</span>
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1) }}
                  className="bg-surface-3 border border-surface-3 text-zinc-300 rounded px-1.5 py-1 outline-none focus:border-primary/40"
                >
                  {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-3">
                <span>{(clampedPage - 1) * pageSize + 1}–{Math.min(clampedPage * pageSize, sorted.length)} of {sorted.length}</span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={clampedPage <= 1}
                    className="flex items-center justify-center w-6 h-6 rounded hover:bg-surface-3 disabled:opacity-30 transition-colors"
                  >
                    <ChevronLeft size={13} />
                  </button>
                  <span className="text-zinc-400">Page {clampedPage} / {totalPages}</span>
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={clampedPage >= totalPages}
                    className="flex items-center justify-center w-6 h-6 rounded hover:bg-surface-3 disabled:opacity-30 transition-colors"
                  >
                    <ChevronRight size={13} />
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
