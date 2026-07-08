'use client'

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowUp, ArrowDown, Pause, Loader2 } from 'lucide-react'
import QueueThumb from './QueueThumb'
import QueuePipeline from './QueuePipeline'
import { formatRelative } from '@/lib/utils'
import type { QueueItem, QueueAgentStat } from '@/lib/types'

type SortKey = 'path' | 'type' | 'ingestedAt'

interface Props {
  items: QueueItem[]
  agentStats: Record<string, QueueAgentStat>
  title: string
  countClass: string
  limit?: number
  allowPause?: boolean
  pulse?: boolean
  hideWhenEmpty?: boolean
  emptyMessage?: string
}

const filename = (p: string) => p.split('/').pop() ?? p

export default function QueueTable({
  items, agentStats, title, countClass, limit, allowPause = false, pulse = false,
  hideWhenEmpty = true, emptyMessage = 'No items',
}: Props) {
  const router = useRouter()
  const [sortKey, setSortKey] = useState<SortKey>('ingestedAt')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<Set<string>>(new Set())

  const sorted = useMemo(() => {
    const copy = [...items]
    copy.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'ingestedAt') {
        cmp = new Date(a.ingestedAt).getTime() - new Date(b.ingestedAt).getTime()
      } else if (sortKey === 'type') {
        cmp = a.type.localeCompare(b.type)
      } else {
        cmp = filename(a.path).localeCompare(filename(b.path))
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return limit ? copy.slice(0, limit) : copy
  }, [items, sortKey, sortDir, limit])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'ingestedAt' ? 'desc' : 'asc')
    }
  }

  const allSelected = sorted.length > 0 && sorted.every((i) => selected.has(i.path))
  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(sorted.map((i) => i.path)))
  }
  const toggleSelect = (p: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p); else next.add(p)
      return next
    })
  }

  const pauseProcessing = async (paths: string[]) => {
    setBusy((prev) => new Set([...prev, ...paths]))
    try {
      const res = await fetch('/api/queue/pause', {
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

  const SortHeader = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      className="px-4 py-2 text-left cursor-pointer select-none hover:text-zinc-300"
      onClick={() => toggleSort(k)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortKey === k && (sortDir === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
      </span>
    </th>
  )

  if (items.length === 0 && hideWhenEmpty) return null

  return (
    <div className="panel mb-6 overflow-hidden">
      <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {pulse && <span className="w-2 h-2 rounded-full bg-danger animate-pulse" />}
          <span className={`text-sm font-semibold ${countClass}`}>{title} ({items.length})</span>
        </div>
        {selected.size > 0 && allowPause && (
          <button
            type="button"
            onClick={() => pauseProcessing([...selected])}
            disabled={[...selected].some((p) => busy.has(p))}
            title="Pause queue processing for the selected items"
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded bg-danger/10 text-danger border border-danger/30 hover:bg-danger/20 transition-colors disabled:opacity-50"
          >
            <Pause size={11} /> Pause {selected.size} selected
          </button>
        )}
      </div>
      {sorted.length === 0 ? (
        <div className="p-6 text-center text-zinc-500 text-sm">{emptyMessage}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-surface-3 text-zinc-500">
                {allowPause && (
                  <th className="px-4 py-2 text-left">
                    <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} className="cursor-pointer" />
                  </th>
                )}
                <th className="px-4 py-2 text-left"></th>
                <SortHeader label="File" k="path" />
                <SortHeader label="Type" k="type" />
                <SortHeader label="Ingested" k="ingestedAt" />
                <th className="px-4 py-2 text-left">Pipeline</th>
                {allowPause && <th className="px-4 py-2 text-left"></th>}
              </tr>
            </thead>
            <tbody>
              {sorted.map((item) => (
                <tr key={item.path} className="border-b border-surface-3/50 hover:bg-surface-2">
                  {allowPause && (
                    <td className="px-4 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(item.path)}
                        onChange={() => toggleSelect(item.path)}
                        className="cursor-pointer"
                      />
                    </td>
                  )}
                  <td className="px-4 py-2"><QueueThumb path={item.path} /></td>
                  <td className="px-4 py-2 font-mono text-zinc-300">{filename(item.path)}</td>
                  <td className="px-4 py-2 text-zinc-400">{item.type}</td>
                  <td className="px-4 py-2 text-zinc-400">{formatRelative(item.ingestedAt)}</td>
                  <td className="px-4 py-2"><QueuePipeline item={item} agentStats={agentStats} /></td>
                  {allowPause && (
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        title="Pause queue processing for this item"
                        onClick={() => pauseProcessing([item.path])}
                        disabled={busy.has(item.path)}
                        className="flex items-center justify-center w-6 h-6 rounded text-zinc-500 hover:text-danger hover:bg-danger/10 transition-colors disabled:opacity-50"
                      >
                        {busy.has(item.path) ? <Loader2 size={12} className="animate-spin" /> : <Pause size={12} />}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
