export const dynamic = 'force-dynamic'

import { readQueue, readAgents } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import QueueBoard from '@/components/queue/QueueBoard'
import { Inbox } from 'lucide-react'
import type { QueueAgentStat } from '@/lib/types'

export default async function QueuePage() {
  const queue = readQueue()

  // Per-agent runtime stats (last run / times ran) for the pipeline tooltips,
  // keyed by registry agent name (= queue slot name).
  const agentStats: Record<string, QueueAgentStat> = {}
  for (const a of readAgents()) {
    agentStats[a.name] = { status: a.status, lastRun: a.lastRun, totalRuns: a.totalRuns }
  }

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Inbox}
        title="Queue"
        subtitle="inbox-queue.json state — pending, done, and stuck items"
      />

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Total</div>
          <div className="text-3xl font-mono font-semibold text-zinc-100">{queue.total}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Pending</div>
          <div className="text-3xl font-mono font-semibold text-warning">{queue.pending}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Paused</div>
          <div className="text-3xl font-mono font-semibold text-neutral">{queue.paused}</div>
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

      <QueueBoard items={queue.items} agentStats={agentStats} byType={queue.byType} />
    </div>
  )
}
