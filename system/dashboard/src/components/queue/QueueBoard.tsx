'use client'

import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import QueueTable from './QueueTable'
import { isDone, isPaused, isStuck } from '@/lib/queue-status'
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
  const [showPaused, setShowPaused] = useState(false)

  const toggleType = (t: string) => {
    setTypes((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t); else next.add(t)
      return next
    })
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return items
      .filter((i) => types.size === 0 || types.has(i.type))
      .filter((i) => !q || filename(i.path).toLowerCase().includes(q))
  }, [items, search, types])

  const stuckItems = filtered.filter(isStuck)
  const pausedItems = filtered.filter(isPaused)
  const pendingItems = filtered.filter((i) => !isDone(i) && !isStuck(i) && !isPaused(i))
  const doneItems = filtered.filter(isDone)

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
        <button
          type="button"
          onClick={() => setShowPaused((v) => !v)}
          className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
            showPaused
              ? 'bg-neutral/15 text-neutral border-neutral/40'
              : 'bg-surface-2 text-zinc-400 border-surface-3 hover:text-zinc-200'
          }`}
        >
          Paused <span className="text-zinc-600">{pausedItems.length}</span>
        </button>
        {(search || types.size > 0) && (
          <span className="text-xs text-zinc-600">{filtered.length} / {items.length}</span>
        )}
      </div>

      <QueueTable
        items={stuckItems}
        agentStats={agentStats}
        title="Stuck Items"
        countClass="text-danger"
        allowPause
        pulse
      />

      <QueueTable
        items={pendingItems}
        agentStats={agentStats}
        title="Pending Items"
        countClass="text-warning"
        limit={50}
        allowPause
      />

      {showPaused && (
        <QueueTable
          items={pausedItems}
          agentStats={agentStats}
          title="Paused Items"
          countClass="text-neutral"
        />
      )}

      <QueueTable
        items={doneItems}
        agentStats={agentStats}
        title="Completed Items"
        countClass="text-success"
        limit={30}
        hideWhenEmpty={false}
        emptyMessage="No completed items"
      />
    </div>
  )
}
