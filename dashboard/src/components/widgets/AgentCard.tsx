'use client'

import { useState } from 'react'
import { Settings } from 'lucide-react'
import type { AgentInfo } from '@/lib/types'
import { formatRelative, formatDuration, agentDisplayName, statusDotClass } from '@/lib/utils'
import StatusBadge from './StatusBadge'
import AgentConfigDialog from '@/components/agents/AgentConfigDialog'

interface AgentCardProps {
  agent: AgentInfo
}

export default function AgentCard({ agent }: AgentCardProps) {
  const [configOpen, setConfigOpen] = useState(false)

  return (
    <>
      <div className="panel p-4 flex flex-col gap-3">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className={`dot ${statusDotClass(agent.status)}`} />
              <span className="font-medium text-zinc-100 text-sm truncate">{agentDisplayName(agent.name)}</span>
            </div>
            {agent.description && (
              <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{agent.description}</p>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0 ml-2">
            <StatusBadge status={agent.status} size="sm" />
            {agent.status !== 'planned' && (
              <button
                onClick={() => setConfigOpen(true)}
                title={`Configure ${agentDisplayName(agent.name)}`}
                className="p-1 rounded text-zinc-600 hover:text-zinc-200 hover:bg-surface-2 transition-colors"
              >
                <Settings size={13} />
              </button>
            )}
          </div>
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
            <span className="text-zinc-300 font-mono" suppressHydrationWarning>{formatRelative(agent.lastRun)}</span>
          </div>
          {agent.status !== 'planned' && (
            <div className="flex justify-between">
              <span>Next run</span>
              <span className="text-zinc-300 font-mono" suppressHydrationWarning>{formatRelative(agent.nextRun)}</span>
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
          {agent.intelligence !== 'none' && (
            <div className="flex justify-between gap-2 min-w-0">
              <span className="shrink-0">Intelligence</span>
              <span className="text-primary font-mono truncate text-right" title={agent.intelligence}>{agent.intelligence}</span>
            </div>
          )}
          {agent.fallbackIntelligence && (
            <div className="flex justify-between gap-2 min-w-0">
              <span className="shrink-0 text-zinc-600">Fallback</span>
              <span className="text-zinc-400 font-mono truncate text-right" title={agent.fallbackIntelligence}>{agent.fallbackIntelligence}</span>
            </div>
          )}
        </div>
      </div>

      <AgentConfigDialog
        agentName={agent.name}
        agentDisplayName={agentDisplayName(agent.name)}
        open={configOpen}
        onClose={() => setConfigOpen(false)}
      />
    </>
  )
}
