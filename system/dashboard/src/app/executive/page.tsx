export const dynamic = 'force-dynamic'

import { readVaultStats, readAgents, readLogs, readLatestReport, readQueue } from '@/lib/vault'
import KPICard from '@/components/widgets/KPICard'
import AgentCard from '@/components/widgets/AgentCard'
import ActivityFeed from '@/components/widgets/ActivityFeed'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import { LayoutDashboard } from 'lucide-react'
import { formatDateTime } from '@/lib/utils'

export default async function ExecutivePage() {
  const [stats, agents, logs, report, queue] = await Promise.all([
    Promise.resolve(readVaultStats()),
    Promise.resolve(readAgents()),
    Promise.resolve(readLogs({ limit: 50 })),
    Promise.resolve(readLatestReport()),
    Promise.resolve(readQueue()),
  ])

  const activeAgents = agents.filter((a) => a.status === 'idle' || a.status === 'running')
  const errorAgents = agents.filter((a) => a.status === 'error')
  const offlineAgents = agents.filter((a) => a.status === 'offline')

  const totalErrors = report
    ? Object.values(report.agentSummaries).reduce((s, a) => s + a.errors, 0)
    : 0
  const totalRuns = report
    ? Object.values(report.agentSummaries).reduce((s, a) => s + a.runs, 0)
    : 0

  const topAgents = agents
    .filter((a) => a.status !== 'planned')
    .slice(0, 6)

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={LayoutDashboard}
        title="Executive Dashboard"
        subtitle={report ? `Daily report for ${report.date} · generated ${formatDateTime(report.generatedAt)}` : 'Nexus Campaigns'}
      />

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
        <KPICard label="Inbox" value={stats.inbox} sub="raw files" accent="neutral" />
        <KPICard label="Processing" value={stats.processing} sub="pending review" accent="warning" />
        <KPICard label="Library" value={stats.library} sub="approved canon" accent="success" />
        <KPICard label="Queue Items" value={queue.total} sub={`${queue.pending} pending`} accent="primary" />
        <KPICard label="Agent Runs" value={totalRuns} sub="last 24h" accent="neutral" />
        <KPICard
          label="Errors"
          value={totalErrors}
          sub="last 24h"
          accent={totalErrors > 0 ? 'danger' : 'success'}
        />
      </div>

      {/* Second row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <KPICard label="Images" value={stats.totalImages} sub="in inbox" accent="neutral" />
        <KPICard label="NPCs" value={stats.totalNpcs} sub="in library" accent="success" />
        <KPICard label="Active Agents" value={activeAgents.length} sub={`${offlineAgents.length} offline`} accent="primary" />
        <KPICard label="Stuck" value={queue.stuck} sub="items >24h" accent={queue.stuck > 0 ? 'danger' : 'success'} />
      </div>

      {/* Pipeline bar */}
      <div className="panel p-4 mb-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">Pipeline Flow</div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-2">
          {[
            { label: 'Inbox', count: stats.inbox, color: 'bg-neutral/60' },
            { label: 'Processing', count: stats.processing, color: 'bg-warning/60' },
            { label: 'Library', count: stats.library, color: 'bg-success/60' },
            { label: 'Campaigns', count: stats.campaigns, color: 'bg-primary/60' },
            { label: 'Assets', count: stats.assets, color: 'bg-purple-500/60' },
          ].map((stage, i) => (
            <div key={stage.label} className="flex items-center gap-2 sm:flex-1">
              <div className="flex-1">
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-zinc-400">{stage.label}</span>
                  <span className="font-mono text-zinc-300">{stage.count}</span>
                </div>
                <div className="h-2 bg-surface-3 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${stage.color} rounded-full`}
                    style={{ width: `${Math.min(100, (stage.count / Math.max(stats.inbox, 1)) * 100)}%` }}
                  />
                </div>
              </div>
              {i < 4 && <span className="hidden sm:block text-zinc-600 text-sm">›</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Agent grid */}
        <div className="lg:col-span-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">Active Agents</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {topAgents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        </div>

        {/* Activity feed */}
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">Activity Feed</div>
          <div className="panel overflow-hidden">
            <ActivityFeed logs={logs} maxHeight="500px" />
          </div>
        </div>
      </div>

      {/* Error agents warning */}
      {errorAgents.length > 0 && (
        <div className="mt-6 p-4 rounded-lg border border-danger/30 bg-danger/5">
          <div className="text-sm font-semibold text-danger mb-2">Agents in Error State</div>
          <div className="flex flex-wrap gap-2">
            {errorAgents.map((a) => (
              <span key={a.id} className="text-xs px-2 py-1 rounded bg-danger/10 text-danger border border-danger/20 font-mono">
                {a.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
