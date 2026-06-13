import { PageHeader } from '@/components/widgets/PageHeader'
import { KPICard } from '@/components/widgets/KPICard'
import { AgentCard } from '@/components/widgets/AgentCard'
import { ActivityFeed } from '@/components/widgets/ActivityFeed'
import { relativeTime } from '@/lib/utils'
import { getVaultStats, getAgentInfo, getQueueStats, latestReport, parseLog } from '@/lib/vault'
import type { DailyReport } from '@/lib/types'
import { AutoRefresh } from '@/components/AutoRefresh'

function fetchData() {
  const stats  = getVaultStats()
  const agents = getAgentInfo()
  const queue  = getQueueStats()
  const report = latestReport() as DailyReport | null
  const logs   = parseLog(60)
  return { stats, agents, queue, report, logs }
}

export const dynamic = 'force-dynamic'

export default function ExecutiveDashboard() {
  const { stats, agents, queue, report, logs } = fetchData()

  const totalErrors24h = agents.reduce((s, a) => s + a.errors24h, 0)
  const agentsWithErrors = agents.filter(a => a.errors24h > 0)
  const pendingReview = report?.vaultHealth?.pendingReview?.length ?? 0
  const orphans = report?.vaultHealth?.orphans?.length ?? 0
  const stuckItems = queue?.byStatus.stuck ?? 0

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader
        title="Executive Dashboard"
        icon="⬡"
        subtitle="DM Knowledge Factory · Mission Control"
      />

      <div className="p-6 space-y-6">

        {/* KPI Row */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <KPICard
            label="Library Entities"
            value={stats?.folders.library ?? '—'}
            icon="📚"
            sub="approved canon"
            accent="success"
          />
          <KPICard
            label="Pending Review"
            value={pendingReview}
            icon="👁"
            sub="awaiting human"
            accent={pendingReview > 10 ? 'warning' : 'neutral'}
          />
          <KPICard
            label="Inbox Files"
            value={stats?.folders.inbox ?? '—'}
            icon="📥"
            sub="in 00-Inbox"
            accent="primary"
          />
          <KPICard
            label="Processing"
            value={stats?.folders.processing ?? '—'}
            icon="⚙️"
            sub="drafts in pipeline"
            accent="primary"
          />
          <KPICard
            label="Errors 24h"
            value={totalErrors24h}
            icon="⚡"
            sub={agentsWithErrors.map(a => a.name).join(', ') || 'all clear'}
            accent={totalErrors24h > 0 ? 'danger' : 'success'}
          />
          <KPICard
            label="Stuck Items"
            value={stuckItems}
            icon="🔒"
            sub="blocked > 2h"
            accent={stuckItems > 0 ? 'warning' : 'neutral'}
          />
        </div>

        {/* Second row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KPICard
            label="Images Classified"
            value={stats?.images.classified ?? '—'}
            icon="🖼️"
            sub={`${stats?.images.withTokens ?? 0} tokens generated`}
            accent="neutral"
          />
          <KPICard
            label="NPCs Generated"
            value={stats?.npcs.approved ?? '—'}
            icon="🧙"
            sub="across all scenarios"
            accent="neutral"
          />
          <KPICard
            label="Orphan Entities"
            value={orphans}
            icon="🔗"
            sub="no relationships"
            accent={orphans > 5 ? 'warning' : 'neutral'}
          />
          <KPICard
            label="Campaign Files"
            value={stats?.folders.campaigns ?? '—'}
            icon="⚔️"
            sub="in 03-Campaigns"
            accent="neutral"
          />
        </div>

        {/* Pipeline summary + Agent health */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Pipeline flow */}
          <div className="card p-4">
            <div className="section-title mb-3">Pipeline Flow</div>
            <PipelineBar
              stages={[
                { label: '00-Inbox',     count: stats?.folders.inbox ?? 0,      color: 'bg-neutral' },
                { label: 'Processing',   count: stats?.folders.processing ?? 0, color: 'bg-primary' },
                { label: 'Review',       count: pendingReview,                  color: 'bg-warning' },
                { label: '02-Library',   count: stats?.folders.library ?? 0,    color: 'bg-success' },
              ]}
            />
          </div>

          {/* Queue health */}
          <div className="card p-4">
            <div className="section-title mb-3">Queue Health</div>
            {queue ? (
              <div className="space-y-2">
                <QueueRow label="Total items"  value={queue.total}             color="text-white" />
                <QueueRow label="Pending"      value={queue.byStatus.pending}  color="text-warning" />
                <QueueRow label="Completed"    value={queue.byStatus.done}     color="text-success" />
                <QueueRow label="Stuck > 2h"   value={queue.byStatus.stuck}    color={queue.byStatus.stuck > 0 ? 'text-danger' : 'text-neutral'} />
                <div className="border-t border-surface-3 pt-2 mt-2">
                  <QueueRow label="Images"    value={queue.byType.image}    color="text-zinc-400" />
                  <QueueRow label="Documents" value={queue.byType.document} color="text-zinc-400" />
                </div>
              </div>
            ) : <div className="text-neutral text-sm">No queue data</div>}
          </div>

          {/* Report summary */}
          <div className="card p-4">
            <div className="section-title mb-3">Last Report</div>
            {report ? (
              <div className="space-y-2">
                <QueueRow label="Total runs"  value={report.summary.totalRuns}    color="text-white" />
                <QueueRow label="Errors"      value={report.summary.totalErrors}  color={report.summary.totalErrors > 0 ? 'text-danger' : 'text-success'} />
                <QueueRow label="Warnings"    value={report.summary.totalWarnings} color={report.summary.totalWarnings > 0 ? 'text-warning' : 'text-neutral'} />
                <div className="text-xs text-neutral mt-2 pt-2 border-t border-surface-3">
                  Generated {relativeTime(report.generatedAt)}
                </div>
              </div>
            ) : <div className="text-neutral text-sm">No report yet</div>}
          </div>

        </div>

        {/* Agent health grid */}
        <div>
          <div className="section-title mb-3">Agent Health</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {agents.map(agent => (
              <AgentCard key={agent.id} agent={agent} compact />
            ))}
          </div>
        </div>

        {/* Recent activity */}
        <div className="card">
          <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between">
            <div className="section-title">Recent Activity</div>
            <span className="text-xs text-neutral">{logs.length} entries</span>
          </div>
          <ActivityFeed logs={logs} maxItems={40} />
        </div>

      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function PipelineBar({ stages }: { stages: Array<{ label: string; count: number; color: string }> }) {
  const max = Math.max(...stages.map(s => s.count), 1)
  return (
    <div className="space-y-2">
      {stages.map(s => (
        <div key={s.label}>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-zinc-400">{s.label}</span>
            <span className="text-white font-medium tabular-nums">{s.count}</span>
          </div>
          <div className="h-1.5 bg-surface-3 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${s.color}`}
              style={{ width: `${(s.count / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function QueueRow({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-zinc-400">{label}</span>
      <span className={`font-medium tabular-nums ${color}`}>{value}</span>
    </div>
  )
}
