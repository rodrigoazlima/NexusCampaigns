import { PageHeader } from '@/components/widgets/PageHeader'
import { cn, relativeTime, statusBadge, fmtDate } from '@/lib/utils'
import type { QueueItem } from '@/lib/types'
import { getQueueStats } from '@/lib/vault'
import { AutoRefresh } from '@/components/AutoRefresh'

export const dynamic = 'force-dynamic'

function ageLabel(ms: number): string {
  const h = ms / 3_600_000
  if (h < 1)  return `${Math.round(ms / 60_000)}m`
  if (h < 24) return `${Math.round(h)}h`
  return `${Math.round(h / 24)}d`
}

function ageColor(ms: number, isStuck: boolean): string {
  if (isStuck) return 'text-danger'
  if (ms > 3_600_000) return 'text-warning'
  return 'text-neutral'
}

export default function QueuePage() {
  const data = getQueueStats()

  const stuckItems    = data.items.filter(i => i.isStuck)
  const pendingItems  = data.items.filter(i => !i.isStuck && Object.values(i.agents).some(s => s === 'pending'))
  const completedItems = data.items.filter(i => Object.values(i.agents).every(s => s === 'done' || s === 'skip'))

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader title="Queue Dashboard" icon="📥" subtitle="inbox-queue.json — real-time asset pipeline state" />

      <div className="p-6 space-y-6">

        {/* Summary */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Total',     value: data.total,              color: 'text-white' },
            { label: 'Pending',   value: data.byStatus.pending,   color: 'text-warning' },
            { label: 'Completed', value: data.byStatus.done,      color: 'text-success' },
            { label: 'Stuck > 2h',value: data.byStatus.stuck,     color: data.byStatus.stuck > 0 ? 'text-danger' : 'text-neutral' },
          ].map(s => (
            <div key={s.label} className="card p-4 text-center">
              <div className={`text-2xl font-semibold tabular-nums ${s.color}`}>{s.value}</div>
              <div className="text-xs text-neutral mt-1">{s.label}</div>
            </div>
          ))}
        </div>

        {/* By type */}
        <div className="grid grid-cols-3 gap-3">
          {(Object.entries(data.byType) as [string, number][]).map(([type, count]) => (
            <div key={type} className="card p-3 flex items-center justify-between">
              <span className="text-sm text-zinc-400 capitalize">{type}</span>
              <span className="font-semibold text-white tabular-nums">{count}</span>
            </div>
          ))}
        </div>

        {/* Stuck items — highest priority */}
        {stuckItems.length > 0 && (
          <div className="card border-danger/30">
            <div className="px-4 py-3 border-b border-danger/20 flex items-center gap-2">
              <span className="dot-error" />
              <div className="section-title text-danger">Stuck Items ({stuckItems.length})</div>
            </div>
            <QueueTable items={stuckItems} />
          </div>
        )}

        {/* Pending */}
        {pendingItems.length > 0 && (
          <div className="card">
            <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between">
              <div className="section-title">Pending ({pendingItems.length})</div>
            </div>
            <QueueTable items={pendingItems} />
          </div>
        )}

        {/* Completed */}
        <div className="card">
          <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between">
            <div className="section-title">Completed ({completedItems.length})</div>
          </div>
          <QueueTable items={completedItems.slice(0, 50)} />
        </div>

      </div>
    </div>
  )
}

function QueueTable({ items }: { items: QueueItem[] }) {
  if (items.length === 0) return <div className="px-4 py-6 text-neutral text-sm text-center">No items</div>

  const allAgentKeys = [...new Set(items.flatMap(i => Object.keys(i.agents)))]

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-surface-3 text-left">
            <th className="px-4 py-2 text-neutral font-medium">File</th>
            <th className="px-4 py-2 text-neutral font-medium">Type</th>
            <th className="px-4 py-2 text-neutral font-medium">Age</th>
            <th className="px-4 py-2 text-neutral font-medium">Ingested</th>
            {allAgentKeys.map(k => (
              <th key={k} className="px-3 py-2 text-neutral font-medium capitalize">{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const fileName = item.path.split('/').pop() ?? item.path
            return (
              <tr key={item.path} className={cn('table-row-hover border-b border-surface-3/50', item.isStuck && 'bg-danger/5')}>
                <td className="px-4 py-2 font-mono max-w-xs truncate" title={item.path}>
                  {item.isStuck && <span className="mr-1 text-danger">⚠</span>}
                  {fileName}
                </td>
                <td className="px-4 py-2">
                  <span className={cn('badge', statusBadge(item.type))}>{item.type}</span>
                </td>
                <td className={cn('px-4 py-2 tabular-nums font-medium', ageColor(item.ageMs, item.isStuck))}>
                  {ageLabel(item.ageMs)}
                </td>
                <td className="px-4 py-2 text-neutral">{fmtDate(item.ingestedAt)}</td>
                {allAgentKeys.map(k => (
                  <td key={k} className="px-3 py-2">
                    <span className={cn('badge', statusBadge(item.agents[k] ?? 'skip'))}>
                      {item.agents[k] ?? '—'}
                    </span>
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
