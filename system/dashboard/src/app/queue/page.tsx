export const dynamic = 'force-dynamic'

import { readQueue, readAgents } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import QueuePipeline from '@/components/queue/QueuePipeline'
import QueueThumb from '@/components/queue/QueueThumb'
import { Inbox } from 'lucide-react'
import { formatRelative } from '@/lib/utils'
import type { QueueItem, QueueAgentStat } from '@/lib/types'

function isStuck(item: QueueItem): boolean {
  const cutoff = Date.now() - 24 * 60 * 60 * 1000
  const t = new Date(item.ingestedAt).getTime()
  return (
    !isNaN(t) &&
    t < cutoff &&
    Object.values(item.agents).some((s) => s === 'pending')
  )
}

function isDone(item: QueueItem): boolean {
  return Object.values(item.agents).every((s) => s === 'done' || s === 'skip')
}

export default async function QueuePage() {
  const queue = readQueue()

  // Per-agent runtime stats (last run / times ran) for the pipeline tooltips,
  // keyed by registry agent name (= queue slot name).
  const agentStats: Record<string, QueueAgentStat> = {}
  for (const a of readAgents()) {
    agentStats[a.name] = { status: a.status, lastRun: a.lastRun, totalRuns: a.totalRuns }
  }

  const stuckItems = queue.items.filter(isStuck)
  const pendingItems = queue.items.filter((i) => !isDone(i) && !isStuck(i))
  const doneItems = queue.items.filter(isDone)

  const filename = (p: string) => p.split('/').pop() ?? p

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Inbox}
        title="Queue"
        subtitle="inbox-queue.json state — pending, done, and stuck items"
      />

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Total</div>
          <div className="text-3xl font-mono font-semibold text-zinc-100">{queue.total}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Pending</div>
          <div className="text-3xl font-mono font-semibold text-warning">{queue.pending}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Done</div>
          <div className="text-3xl font-mono font-semibold text-success">{queue.done}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Stuck (&gt;24h)</div>
          <div className={`text-3xl font-mono font-semibold ${queue.stuck > 0 ? 'text-danger' : 'text-zinc-400'}`}>
            {queue.stuck}
          </div>
        </div>
      </div>

      {/* By Type */}
      <div className="panel p-4 mb-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">By Type</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(queue.byType).map(([type, count]) => (
            <div key={type} className="flex items-center gap-2 px-3 py-1.5 bg-surface-2 rounded-md">
              <span className="text-sm text-zinc-300">{type}</span>
              <span className="text-sm font-mono font-semibold text-primary">{count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Stuck Table */}
      {stuckItems.length > 0 && (
        <div className="panel mb-6 overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-danger animate-pulse" />
            <span className="text-sm font-semibold text-danger">Stuck Items ({stuckItems.length})</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-3 text-zinc-500">
                  <th className="px-4 py-2 text-left"></th>
                  <th className="px-4 py-2 text-left">File</th>
                  <th className="px-4 py-2 text-left">Type</th>
                  <th className="px-4 py-2 text-left">Ingested</th>
                  <th className="px-4 py-2 text-left">Pipeline</th>
                </tr>
              </thead>
              <tbody>
                {stuckItems.map((item) => (
                  <tr key={item.path} className="border-b border-surface-3/50 hover:bg-surface-2">
                    <td className="px-4 py-2"><QueueThumb path={item.path} /></td>
                    <td className="px-4 py-2 font-mono text-danger">{filename(item.path)}</td>
                    <td className="px-4 py-2 text-zinc-400">{item.type}</td>
                    <td className="px-4 py-2 text-zinc-400">{formatRelative(item.ingestedAt)}</td>
                    <td className="px-4 py-2">
                      <QueuePipeline item={item} agentStats={agentStats} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pending Table */}
      {pendingItems.length > 0 && (
        <div className="panel mb-6 overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <span className="text-sm font-semibold text-warning">Pending Items ({pendingItems.length})</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-3 text-zinc-500">
                  <th className="px-4 py-2 text-left"></th>
                  <th className="px-4 py-2 text-left">File</th>
                  <th className="px-4 py-2 text-left">Type</th>
                  <th className="px-4 py-2 text-left">Ingested</th>
                  <th className="px-4 py-2 text-left">Pipeline</th>
                </tr>
              </thead>
              <tbody>
                {pendingItems.slice(0, 50).map((item) => (
                  <tr key={item.path} className="border-b border-surface-3/50 hover:bg-surface-2">
                    <td className="px-4 py-2"><QueueThumb path={item.path} /></td>
                    <td className="px-4 py-2 font-mono text-zinc-300">{filename(item.path)}</td>
                    <td className="px-4 py-2 text-zinc-400">{item.type}</td>
                    <td className="px-4 py-2 text-zinc-400">{formatRelative(item.ingestedAt)}</td>
                    <td className="px-4 py-2">
                      <QueuePipeline item={item} agentStats={agentStats} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Done table */}
      <div className="panel overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-3">
          <span className="text-sm font-semibold text-success">Completed Items ({doneItems.length})</span>
        </div>
        {doneItems.length === 0 ? (
          <div className="p-6 text-center text-zinc-500 text-sm">No completed items</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-3 text-zinc-500">
                  <th className="px-4 py-2 text-left"></th>
                  <th className="px-4 py-2 text-left">File</th>
                  <th className="px-4 py-2 text-left">Type</th>
                  <th className="px-4 py-2 text-left">Ingested</th>
                  <th className="px-4 py-2 text-left">Pipeline</th>
                </tr>
              </thead>
              <tbody>
                {doneItems.slice(0, 30).map((item) => (
                  <tr key={item.path} className="border-b border-surface-3/50 hover:bg-surface-2">
                    <td className="px-4 py-2"><QueueThumb path={item.path} /></td>
                    <td className="px-4 py-2 font-mono text-zinc-400">{filename(item.path)}</td>
                    <td className="px-4 py-2 text-zinc-500">{item.type}</td>
                    <td className="px-4 py-2 text-zinc-500">{formatRelative(item.ingestedAt)}</td>
                    <td className="px-4 py-2">
                      <QueuePipeline item={item} agentStats={agentStats} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
