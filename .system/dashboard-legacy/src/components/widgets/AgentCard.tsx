import { cn, relativeTime, nextRunTime, statusBadge } from '@/lib/utils'
import type { AgentInfo } from '@/lib/types'
import { AgentEditButton } from './AgentEditButton'

interface AgentCardProps {
  agent: AgentInfo
  compact?: boolean
}

const statusDot: Record<string, string> = {
  idle:    'dot-idle',
  running: 'dot-live',
  error:   'dot-error',
  offline: 'dot-idle',
}

export function AgentCard({ agent, compact }: AgentCardProps) {
  const successRate = agent.runs24h > 0
    ? Math.round((agent.completedRuns24h / agent.runs24h) * 100)
    : null

  return (
    <div className={cn('card p-4 flex flex-col gap-3', compact && 'p-3 gap-2')}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className={statusDot[agent.status]} />
          <span className="font-medium text-sm text-white">{agent.name}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <AgentEditButton
            agentId={agent.id}
            agentName={agent.name}
            currentModel={agent.model}
            currentInterval={agent.intervalSeconds}
          />
          <span className={cn('badge', statusBadge(agent.status))}>
            {agent.status}
          </span>
        </div>
      </div>

      {!compact && (
        <p className="text-xs text-neutral leading-relaxed">{agent.description}</p>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Runs 24h" value={agent.runs24h} />
        <Stat label="Errors" value={agent.errors24h} danger={agent.errors24h > 0} />
        <Stat label="Success" value={successRate !== null ? `${successRate}%` : '—'} />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-neutral border-t border-surface-3 pt-2">
        <span>Last run: {relativeTime(agent.lastRun)}</span>
        <span>Next: {nextRunTime(agent.lastRun, agent.intervalSeconds)}</span>
      </div>
      {agent.model && (
        <div className="text-xs text-neutral/60 font-mono truncate">{agent.model}</div>
      )}
    </div>
  )
}

function Stat({ label, value, danger }: { label: string; value: string | number; danger?: boolean }) {
  return (
    <div className="bg-surface-2 rounded p-2 text-center">
      <div className={cn('text-sm font-semibold tabular-nums', danger ? 'text-danger' : 'text-white')}>
        {value}
      </div>
      <div className="text-xs text-neutral mt-0.5">{label}</div>
    </div>
  )
}
