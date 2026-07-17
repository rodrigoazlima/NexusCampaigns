'use client'

import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import QueueTable from './QueueTable'
import { QUEUE_STATUSES, STATUS_META, resolveStatus } from '@/lib/queue-status'
import type { QueueItem, QueueAgentStat } from '@/lib/types'

interface Props {
  items: QueueItem[]
  agentStats: Record<string, QueueAgentStat>
  byType: Record<string, number>
}

const filename = (p: string) => p.split('/').pop() ?? p

export default function QueueBoard({ items, agentStats, byType }: Props) {
  const [search, setSearch] = useState('')
  const [types, setTypes] = useState<Set<string>>(new Set())
  const [statuses, setStatuses] = useState<Set<string>>(new Set())

  const toggleType = (t: string) => {
    setTypes((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t); else next.add(t)
      return next
    })
  }

  const toggleStatus = (s: string) => {
    setStatuses((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s); else next.add(s)
      return next
    })
  }

  // Search + type filtered, before the status narrowing - this is also what
  // status chip counts are computed against.
  const searched = useMemo(() => {
    const q = search.trim().toLowerCase()
    return items
      .filter((i) => types.size === 0 || types.has(i.type))
      .filter((i) => !q || filename(i.path).toLowerCase().includes(q))
  }, [items, search, types])

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const s of QUEUE_STATUSES) counts[s] = 0
    for (const item of searched) counts[resolveStatus(item)]++
    return counts
  }, [searched])

  // Empty status selection = show everything, no filtering applied.
  const visible = useMemo(() => {
    if (statuses.size === 0) return searched
    return searched.filter((i) => statuses.has(resolveStatus(i)))
  }, [searched, statuses])

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-zinc-600" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by filename…"
            className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 pl-7 pr-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors w-56"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {Object.entries(byType).map(([type, count]) => (
            <button
              key={type}
              type="button"
              onClick={() => toggleType(type)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                types.has(type)
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'bg-surface-2 text-zinc-400 border-surface-3 hover:text-zinc-200'
              }`}
            >
              {type} <span className="text-zinc-600">{count}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {QUEUE_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              onClick={() => toggleStatus(status)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                statuses.has(status)
                  ? STATUS_META[status].chip
                  : 'bg-surface-2 text-zinc-400 border-surface-3 hover:text-zinc-200'
              }`}
            >
              {STATUS_META[status].label} <span className="text-zinc-600">{statusCounts[status]}</span>
            </button>
          ))}
        </div>
        {(search || types.size > 0 || statuses.size > 0) && (
          <span className="text-xs text-zinc-600">{visible.length} / {items.length}</span>
        )}
      </div>

      <QueueTable items={visible} agentStats={agentStats} />
    </div>
  )
}
