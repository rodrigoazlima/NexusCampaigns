'use client'

import { useEffect, useState } from 'react'
import type { QueueStats } from '@/lib/types'
import { agentDisplayName } from '@/lib/utils'
import { PIPELINE } from '@/components/queue/QueuePipeline'

interface StepCount { agent: string; done: number; total: number }

function summarize(stats: QueueStats): { done: number; total: number; steps: StepCount[] } {
  const steps = PIPELINE.map((agent) => ({
    agent,
    done: stats.items.filter((i) => i.agents[agent] === 'done').length,
    total: stats.items.length,
  }))
  return {
    done: steps.reduce((sum, s) => sum + s.done, 0),
    total: steps.reduce((sum, s) => sum + s.total, 0),
    steps,
  }
}

export default function PipelineProgress({ collapsed }: { collapsed?: boolean }) {
  const [stats, setStats] = useState<QueueStats | null>(null)

  useEffect(() => {
    const load = () => fetch('/api/queue').then((r) => r.json()).then(setStats).catch(() => {})
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  if (!stats || stats.items.length === 0) return null

  const { done, total, steps } = summarize(stats)
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  if (collapsed) {
    return (
      <div className="px-2 py-3 border-t border-surface-3" title={`Pipeline: ${done}/${total} steps done (${pct}%)`}>
        <div className="h-1 rounded-full bg-surface-3 overflow-hidden">
          <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
    )
  }

  return (
    <div className="group relative px-3 py-3 border-t border-surface-3">
      <div className="flex items-center justify-between mb-1.5 text-[10px] font-semibold tracking-widest text-zinc-500 uppercase">
        <span>Pipeline</span>
        <span className="font-mono text-zinc-400">{done}/{total}</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
        <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>

      {/* Hover detail: per-step breakdown */}
      <div className="hidden group-hover:block absolute z-50 bottom-full left-3 right-3 mb-2 p-3 rounded-lg bg-surface-2 border border-surface-3 shadow-2xl">
        <div className="text-[11px] font-semibold text-zinc-100 mb-2">{stats.items.length} item{stats.items.length === 1 ? '' : 's'} in pipeline</div>
        <div className="space-y-1.5">
          {steps.map((s) => (
            <div key={s.agent} className="flex items-center gap-2 text-[10px]">
              <span className="w-16 shrink-0 text-zinc-500 truncate">{agentDisplayName(s.agent)}</span>
              <div className="flex-1 h-1 rounded-full bg-surface-3 overflow-hidden">
                <div
                  className="h-full bg-primary"
                  style={{ width: `${s.total > 0 ? (s.done / s.total) * 100 : 0}%` }}
                />
              </div>
              <span className="w-9 shrink-0 text-right font-mono text-zinc-400">{s.done}/{s.total}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
