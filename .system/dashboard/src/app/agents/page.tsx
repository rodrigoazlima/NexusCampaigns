import { PageHeader } from '@/components/widgets/PageHeader'
import { AgentCard } from '@/components/widgets/AgentCard'
import { ActivityFeed } from '@/components/widgets/ActivityFeed'
import { AgentModelSelect } from '@/components/widgets/AgentModelSelect'
import { relativeTime, nextRunTime, statusBadge, cn } from '@/lib/utils'
import { getAgentInfo, parseLog } from '@/lib/vault'
import { AutoRefresh } from '@/components/AutoRefresh'

export const dynamic = 'force-dynamic'

export default function AgentsPage() {
  const agents = getAgentInfo()
  const logs   = parseLog(300)

  const healthy  = agents.filter(a => a.status === 'idle' || a.status === 'running').length
  const errored  = agents.filter(a => a.status === 'error').length
  const offline  = agents.filter(a => a.status === 'offline').length
  const total24h = agents.reduce((s, a) => s + a.runs24h, 0)

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader title="Agent Monitoring" icon="🤖" subtitle="Health and throughput for all pipeline agents" />

      <div className="p-6 space-y-6">

        {/* Summary row */}
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Total Agents', value: agents.length, color: 'text-white' },
            { label: 'Healthy',  value: healthy, color: 'text-success' },
            { label: 'Errored',  value: errored, color: errored > 0 ? 'text-danger' : 'text-neutral' },
            { label: 'Runs 24h', value: total24h, color: 'text-primary' },
          ].map(s => (
            <div key={s.label} className="card p-4 text-center">
              <div className={`text-2xl font-semibold tabular-nums ${s.color}`}>{s.value}</div>
              <div className="text-xs text-neutral mt-1">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Agent cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {agents.map(agent => <AgentCard key={agent.id} agent={agent} />)}
        </div>

        {/* Detailed table */}
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="section-title">Agent Schedule</div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-3 text-left">
                <Th>Agent</Th>
                <Th>Status</Th>
                <Th>Model</Th>
                <Th>Interval</Th>
                <Th>Last Run</Th>
                <Th>Next Run</Th>
                <Th>Runs 24h</Th>
                <Th>Errors 24h</Th>
              </tr>
            </thead>
            <tbody>
              {agents.map(agent => (
                <tr key={agent.id} className="table-row-hover border-b border-surface-3/50">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-white">{agent.name}</div>
                    <div className="text-xs text-neutral">{agent.script}</div>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={cn('badge', statusBadge(agent.status))}>{agent.status}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <AgentModelSelect agentId={agent.id} currentModel={agent.model} />
                  </td>
                  <td className="px-4 py-2.5 text-neutral tabular-nums">
                    {agent.intervalSeconds >= 3600 ? `${agent.intervalSeconds / 3600}h` : `${agent.intervalSeconds / 60}m`}
                  </td>
                  <td className="px-4 py-2.5 text-neutral">{relativeTime(agent.lastRun)}</td>
                  <td className="px-4 py-2.5 text-neutral">{nextRunTime(agent.lastRun, agent.intervalSeconds)}</td>
                  <td className="px-4 py-2.5 text-white tabular-nums">{agent.runs24h}</td>
                  <td className="px-4 py-2.5">
                    <span className={agent.errors24h > 0 ? 'text-danger font-medium' : 'text-neutral'}>
                      {agent.errors24h}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Live log */}
        <div className="card">
          <div className="px-4 py-3 border-b border-surface-3 flex items-center gap-2">
            <span className="dot-live" />
            <div className="section-title">Live Log Feed</div>
          </div>
          <ActivityFeed logs={logs} maxItems={100} />
        </div>

      </div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-xs font-medium text-neutral uppercase tracking-wide">{children}</th>
}
