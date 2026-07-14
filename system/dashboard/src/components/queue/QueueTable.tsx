'use client'

import { useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowUp, ArrowDown, Pause, Play, RotateCcw, Trash2, Loader2, ChevronLeft, ChevronRight } from 'lucide-react'
import QueueThumb from './QueueThumb'
import QueuePipeline from './QueuePipeline'
import { formatRelative } from '@/lib/utils'
import { STATUS_META, resolveStatus, canPause, canResume, canRetry } from '@/lib/queue-status'
import type { QueueItem, QueueAgentStat } from '@/lib/types'

type SortKey = 'path' | 'type' | 'ingestedAt' | 'updatedAt'

interface Props {
  items: QueueItem[]
  agentStats: Record<string, QueueAgentStat>
}

const filename = (p: string) => p.split('/').pop() ?? p
const PAGE_SIZES = [25, 50, 100]

function SortHeader({ label, active, dir, onClick }: { label: string; active: boolean; dir: 'asc' | 'desc'; onClick: () => void }) {
  return (
    <th
      className="px-4 py-2 text-left cursor-pointer select-none hover:text-zinc-300"
      onClick={onClick}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active && (dir === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
      </span>
    </th>
  )
}

export default function QueueTable({ items, agentStats }: Props) {
  const router = useRouter()
  const [sortKey, setSortKey] = useState<SortKey>('ingestedAt')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [anchorIndex, setAnchorIndex] = useState<number | null>(null)
  const confirmTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  // Filters upstream (QueueBoard) change the `items` array reference — jump
  // back to page 1 so the user isn't stranded on a now out-of-range page.
  // Adjusted during render (not an effect) per React's guidance for state
  // that depends on a prop change: https://react.dev/learn/you-might-not-need-an-effect
  const [prevItems, setPrevItems] = useState(items)
  if (items !== prevItems) {
    setPrevItems(items)
    setPage(1)
    setAnchorIndex(null)
  }

  const armConfirm = (key: string) => {
    setConfirming((prev) => new Set(prev).add(key))
    const existing = confirmTimers.current.get(key)
    if (existing) clearTimeout(existing)
    confirmTimers.current.set(key, setTimeout(() => {
      setConfirming((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
      confirmTimers.current.delete(key)
    }, 4000))
  }
  const disarmConfirm = (key: string) => {
    const existing = confirmTimers.current.get(key)
    if (existing) { clearTimeout(existing); confirmTimers.current.delete(key) }
    setConfirming((prev) => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
  }

  const sorted = useMemo(() => {
    const copy = [...items]
    copy.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'ingestedAt') {
        cmp = new Date(a.ingestedAt).getTime() - new Date(b.ingestedAt).getTime()
      } else if (sortKey === 'updatedAt') {
        cmp = new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime()
      } else if (sortKey === 'type') {
        cmp = a.type.localeCompare(b.type)
      } else {
        cmp = filename(a.path).localeCompare(filename(b.path))
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return copy
  }, [items, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const clampedPage = Math.min(page, totalPages)
  const pageItems = useMemo(
    () => sorted.slice((clampedPage - 1) * pageSize, clampedPage * pageSize),
    [sorted, clampedPage, pageSize],
  )

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'ingestedAt' ? 'desc' : 'asc')
    }
  }

  const pageAllSelected = pageItems.length > 0 && pageItems.every((i) => selected.has(i.path))
  const toggleSelectAllOnPage = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (pageAllSelected) pageItems.forEach((i) => next.delete(i.path))
      else pageItems.forEach((i) => next.add(i.path))
      return next
    })
    setAnchorIndex(null)
  }
  const toggleSelect = (p: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p); else next.add(p)
      return next
    })
  }

  // Explorer/Gmail-style multi-select on the checkbox column:
  //  - plain / ctrl+/cmd+click: toggle just this row (checkboxes are already
  //    additive, so ctrl doesn't need to behave differently from a plain click)
  //  - shift+click: select the contiguous range from the last-clicked row
  //    (within the current page) through this one, adding to — not replacing —
  //    whatever else is already selected
  const handleRowSelectClick = (e: React.MouseEvent, index: number) => {
    const item = pageItems[index]
    if (e.shiftKey && anchorIndex !== null) {
      const [start, end] = anchorIndex < index ? [anchorIndex, index] : [index, anchorIndex]
      const range = pageItems.slice(start, end + 1).map((i) => i.path)
      setSelected((prev) => {
        const next = new Set(prev)
        range.forEach((p) => next.add(p))
        return next
      })
    } else {
      toggleSelect(item.path)
    }
    setAnchorIndex(index)
  }

  const setProcessing = async (endpoint: string, paths: string[]) => {
    setBusy((prev) => new Set([...prev, ...paths]))
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths }),
      })
      if (res.ok) {
        setSelected((prev) => {
          const next = new Set(prev)
          paths.forEach((p) => next.delete(p))
          return next
        })
        router.refresh()
      }
    } finally {
      setBusy((prev) => {
        const next = new Set(prev)
        paths.forEach((p) => next.delete(p))
        return next
      })
    }
  }

  const pauseProcessing = (paths: string[]) => setProcessing('/api/queue/pause', paths)
  const resumeProcessing = (paths: string[]) => setProcessing('/api/queue/resume', paths)
  const retryProcessing = (paths: string[]) => setProcessing('/api/queue/retry', paths)
  const deleteProcessing = (paths: string[]) => {
    paths.forEach(disarmConfirm)
    return setProcessing('/api/queue/delete', paths)
  }

  const handleDeleteClick = (key: string, paths: string[]) => {
    if (confirming.has(key)) {
      deleteProcessing(paths)
    } else {
      armConfirm(key)
    }
  }

  const selectedItems = items.filter((i) => selected.has(i.path))
  const selectedCanPause = selectedItems.some(canPause)
  const selectedCanResume = selectedItems.some(canResume)
  const selectedCanRetry = selectedItems.some(canRetry)

  return (
    <div className="panel overflow-hidden">
      <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between gap-3 min-h-[45px]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-zinc-200">Queue ({items.length})</span>
        </div>
        {selected.size > 0 && (
          <div className="flex items-center gap-2">
            {selectedCanPause && (
              <button
                type="button"
                onClick={() => pauseProcessing([...selected])}
                disabled={[...selected].some((p) => busy.has(p))}
                title="Pause queue processing for the selected items"
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 transition-colors disabled:opacity-50"
              >
                <Pause size={11} /> Pause {selected.size}
              </button>
            )}
            {selectedCanResume && (
              <button
                type="button"
                onClick={() => resumeProcessing([...selected])}
                disabled={[...selected].some((p) => busy.has(p))}
                title="Resume queue processing for the selected items"
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-neutral/10 text-neutral border border-neutral/30 hover:bg-neutral/20 transition-colors disabled:opacity-50"
              >
                <Play size={11} /> Resume {selected.size}
              </button>
            )}
            {selectedCanRetry && (
              <button
                type="button"
                onClick={() => retryProcessing([...selected])}
                disabled={[...selected].some((p) => busy.has(p))}
                title="Retry the failed step for the selected items"
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-danger/10 text-danger border border-danger/30 hover:bg-danger/20 transition-colors disabled:opacity-50"
              >
                <RotateCcw size={11} /> Retry {selected.size}
              </button>
            )}
            <button
              type="button"
              onClick={() => handleDeleteClick('bulk', [...selected])}
              disabled={[...selected].some((p) => busy.has(p))}
              title="Delete the selected items — source, generated token, and thumbnail"
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
          <div className="overflow-x-auto">
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
                  <th className="px-4 py-2 text-left">Pipeline</th>
                  <th className="px-4 py-2 text-left">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((item, index) => {
                  const status = resolveStatus(item)
                  const meta = STATUS_META[status]
                  return (
                    <tr key={item.path} className="border-b border-surface-3/50 hover:bg-surface-2">
                      <td className="px-4 py-2">
                        <input
                          type="checkbox"
                          checked={selected.has(item.path)}
                          onClick={(e) => { e.preventDefault(); handleRowSelectClick(e, index) }}
                          readOnly
                          title="Click to select. Shift-click to select the range."
                          className="cursor-pointer"
                        />
                      </td>
                      <td
                        className={`px-4 py-2 ${item.entityId ? 'cursor-pointer' : ''}`}
                        onClick={() => item.entityId && router.push(`/gm/view/${encodeURIComponent(item.entityId)}`)}
                      >
                        <QueueThumb path={item.path} />
                      </td>
                      <td
                        className={`px-4 py-2 ${item.entityId ? 'cursor-pointer' : ''}`}
                        onClick={() => item.entityId && router.push(`/gm/view/${encodeURIComponent(item.entityId)}`)}
                        title={item.entityId ? 'Open in GM view' : undefined}
                      >
                        <div className={`font-mono text-zinc-300 ${item.entityId ? 'hover:text-primary hover:underline' : ''}`}>
                          {filename(item.path)}
                        </div>
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className={`text-[9px] px-1.5 py-0.5 rounded-full border font-medium ${meta.badge}`}>
                            {meta.label}
                          </span>
                          <span className="text-zinc-600">{item.type}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2 text-zinc-400">{formatRelative(item.ingestedAt)}</td>
                      <td className="px-4 py-2 text-zinc-400">{formatRelative(item.updatedAt)}</td>
                      <td className="px-4 py-2"><QueuePipeline item={item} agentStats={agentStats} /></td>
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-1">
                          {canPause(item) && (
                            <button
                              type="button"
                              title="Pause queue processing for this item"
                              onClick={() => pauseProcessing([item.path])}
                              disabled={busy.has(item.path)}
                              className="flex items-center justify-center w-6 h-6 rounded text-zinc-500 hover:text-warning hover:bg-warning/10 transition-colors disabled:opacity-50"
                            >
                              {busy.has(item.path) ? <Loader2 size={12} className="animate-spin" /> : <Pause size={12} />}
                            </button>
                          )}
                          {canResume(item) && (
                            <button
                              type="button"
                              title="Resume queue processing for this item"
                              onClick={() => resumeProcessing([item.path])}
                              disabled={busy.has(item.path)}
                              className="flex items-center justify-center w-6 h-6 rounded text-zinc-500 hover:text-neutral hover:bg-neutral/10 transition-colors disabled:opacity-50"
                            >
                              {busy.has(item.path) ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                            </button>
                          )}
                          {canRetry(item) && (
                            <button
                              type="button"
                              title="Retry the failed step for this item"
                              onClick={() => retryProcessing([item.path])}
                              disabled={busy.has(item.path)}
                              className="flex items-center justify-center w-6 h-6 rounded text-zinc-500 hover:text-danger hover:bg-danger/10 transition-colors disabled:opacity-50"
                            >
                              {busy.has(item.path) ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                            </button>
                          )}
                          <button
                            type="button"
                            title={confirming.has(item.path) ? 'Click again to permanently delete' : 'Delete this item — source, generated token, and thumbnail'}
                            onClick={() => handleDeleteClick(item.path, [item.path])}
                            disabled={busy.has(item.path)}
                            className={`flex items-center justify-center h-6 px-1.5 rounded transition-colors disabled:opacity-50 ${
                              confirming.has(item.path)
                                ? 'text-danger bg-danger/15 border border-danger/40'
                                : 'text-zinc-500 hover:text-danger hover:bg-danger/10'
                            }`}
                          >
                            {busy.has(item.path) ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                            {confirming.has(item.path) && <span className="ml-1 text-[11px] font-semibold whitespace-nowrap">Confirm?</span>}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="px-4 py-2.5 border-t border-surface-3 flex items-center justify-between gap-3 text-xs text-zinc-500">
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
              <span>
                {(clampedPage - 1) * pageSize + 1}–{Math.min(clampedPage * pageSize, sorted.length)} of {sorted.length}
              </span>
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
  )
}
