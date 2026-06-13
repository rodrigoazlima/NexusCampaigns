import type { AgentInfo } from '@/lib/types'
import { formatRelative, formatDateTime, formatDuration, agentDisplayName, statusDotClass } from '@/lib/utils'
import StatusBadge from './StatusBadge'

interface AgentCardProps {
  agent: AgentInfo
}

export default function AgentCard({ agent }: AgentCardProps) {
  return (
    <div className="panel p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className={`dot ${statusDotClass(agent.status)}`} />
            <span className="font-medium text-zinc-100 text-sm">{agentDisplayName(agent.name)}</span>
          </div>
          {agent.description && (
            <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{agent.description}</p>
          )}
        </div>
        <StatusBadge status={agent.status} size="sm" />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-surface-2 rounded p-2">
          <div className="text-base font-mono font-semibold text-zinc-100">{agent.totalRuns}</div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Runs</div>
        </div>
        <div className="bg-surface-2 rounded p-2">
          <div className="text-base font-mono font-semibold text-zinc-100">{agent.totalProcessed}</div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Items</div>
        </div>
        <div className="bg-surface-2 rounded p-2">
          <div className={`text-base font-mono font-semibold ${agent.totalFailed > 0 ? 'text-danger' : 'text-zinc-100'}`}>
            {agent.totalFailed}
          </div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Failed</div>
        </div>
      </div>

      {/* Timing */}
      <div className="text-xs text-zinc-500 space-y-1">
        <div className="flex justify-between">
          <span>Last run</span>
          <span className="text-zinc-300 font-mono">{formatRelative(agent.lastRun)}</span>
        </div>
        {agent.status !== 'planned' && (
          <div className="flex justify-between">
            <span>Next run</span>
            <span className="text-zinc-300 font-mono">{formatRelative(agent.nextRun)}</span>
          </div>
        )}
        {agent.avgDurationMs > 0 && (
          <div className="flex justify-between">
            <span>Avg duration</span>
            <span className="text-zinc-300 font-mono">{formatDuration(agent.avgDurationMs)}</span>
          </div>
        )}
        <div className="flex justify-between">
          <span>Interval</span>
          <span className="text-zinc-300 font-mono">
            {agent.intervalSeconds >= 3600
              ? `${agent.intervalSeconds / 3600}h`
              : agent.intervalSeconds >= 60
              ? `${agent.intervalSeconds / 60}m`
              : `${agent.intervalSeconds}s`}
          </span>
        </div>
        {agent.llm !== 'none' && (
          <div className="flex justify-between">
            <span>LLM</span>
            <span className="text-primary font-mono">{agent.llm}</span>
          </div>
        )}
      </div>
    </div>
  )
}
