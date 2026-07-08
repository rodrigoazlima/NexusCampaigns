export const dynamic = 'force-dynamic'

import { readAgents, readLogs } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AgentCard from '@/components/widgets/AgentCard'
import ActivityFeed from '@/components/widgets/ActivityFeed'
import AutoRefresh from '@/components/AutoRefresh'
import { AgentConfigButton } from '@/components/agents/AgentConfigButton'
import { Bot } from 'lucide-react'
import Link from 'next/link'
import { agentDisplayName, formatDateTime, formatDuration } from '@/lib/utils'

// Agents with a dedicated /agents/{name} detail page.
const DETAIL_PAGES = new Set(['vision'])

export default async function AgentsPage() {
  const [agents, logs] = await Promise.all([
    Promise.resolve(readAgents()),
    Promise.resolve(readLogs({ limit: 80 })),
  ])

  const activeAgents = agents.filter((a) => a.status !== 'planned')
  const plannedAgents = agents.filter((a) => a.status === 'planned')

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Bot}
        title="Agent Monitoring"
        subtitle={`${activeAgents.length} active · ${plannedAgents.length} planned`}
      />

      {/* Agent Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-8">
        {activeAgents.map((agent) => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>

      {/* Schedule Table */}
      <div className="panel mb-6 overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-3">
          <div className="text-sm font-semibold text-zinc-200">Schedule</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-surface-3 text-zinc-500">
                <th className="px-4 py-2 text-left">Agent</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Interval</th>
                <th className="px-4 py-2 text-left">Intelligence</th>
                <th className="px-4 py-2 text-left">Last Run</th>
                <th className="px-4 py-2 text-right">Runs</th>
                <th className="px-4 py-2 text-right">Avg Duration</th>
                <th className="px-4 py-2 text-right">Failed</th>
                <th className="px-4 py-2 text-right">Config</th>
              </tr>
            </thead>
            <tbody>
              {activeAgents.map((agent) => (
                <tr key={agent.id} className="border-b border-surface-3/50 hover:bg-surface-2">
                  <td className="px-4 py-2 font-medium text-zinc-200">
                    {DETAIL_PAGES.has(agent.name) ? (
                      <Link href={`/agents/${agent.name}`} className="hover:text-primary hover:underline">
                        {agentDisplayName(agent.name)}
                      </Link>
                    ) : (
                      agentDisplayName(agent.name)
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${
                      agent.status === 'idle' ? 'bg-success/10 text-success' :
                      agent.status === 'running' ? 'bg-success/20 text-success' :
                      agent.status === 'error' ? 'bg-danger/10 text-danger' :
                      'bg-zinc-700 text-zinc-400'
                    }`}>
                      {agent.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-zinc-400">
                    {agent.intervalSeconds >= 3600
                      ? `${agent.intervalSeconds / 3600}h`
                      : `${agent.intervalSeconds / 60}m`}
                  </td>
                  <td className="px-4 py-2">
                    {agent.intelligence !== 'none' ? (
                      <div>
                        <span className="text-primary font-mono">{agent.intelligence}</span>
                        {agent.fallbackIntelligence && (
                          <div className="text-zinc-500 font-mono text-[10px] mt-0.5">↳ {agent.fallbackIntelligence}</div>
                        )}
                      </div>
                    ) : (
                      <span className="text-zinc-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 font-mono text-zinc-400">{formatDateTime(agent.lastRun)}</td>
                  <td className="px-4 py-2 font-mono text-zinc-300 text-right">{agent.totalRuns}</td>
                  <td className="px-4 py-2 font-mono text-zinc-400 text-right">
                    {agent.avgDurationMs > 0 ? formatDuration(agent.avgDurationMs) : '—'}
                  </td>
                  <td className={`px-4 py-2 font-mono text-right ${agent.totalFailed > 0 ? 'text-danger' : 'text-zinc-500'}`}>
                    {agent.totalFailed}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <AgentConfigButton agent={agent} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Planned */}
      {plannedAgents.length > 0 && (
        <div className="panel mb-6 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">Planned Agents</div>
          <div className="flex flex-wrap gap-2">
            {plannedAgents.map((a) => (
              <div key={a.id} className="px-3 py-2 bg-surface-2 rounded-lg border border-surface-3">
                <div className="text-sm text-zinc-400">{agentDisplayName(a.name)}</div>
                {a.description && <div className="text-xs text-zinc-600 mt-0.5">{a.description}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live log */}
      <div className="panel overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-3">
          <div className="text-sm font-semibold text-zinc-200">Live Log</div>
        </div>
        <ActivityFeed logs={logs} maxHeight="400px" />
      </div>
    </div>
  )
}
