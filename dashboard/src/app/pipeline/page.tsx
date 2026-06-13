export const dynamic = 'force-dynamic'

import { readPipeline, readVaultStats } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import { GitBranch, ArrowRight } from 'lucide-react'

export default async function PipelinePage() {
  const [pipeline, stats] = await Promise.all([
    Promise.resolve(readPipeline()),
    Promise.resolve(readVaultStats()),
  ])

  const total = pipeline.stages.reduce((s, st) => s + st.count, 0) || 1

  const stageColors: Record<string, string> = {
    Inbox: 'border-neutral/40 bg-neutral/5',
    Processing: 'border-warning/40 bg-warning/5',
    Library: 'border-success/40 bg-success/5',
    Campaigns: 'border-primary/40 bg-primary/5',
    Assets: 'border-purple-500/40 bg-purple-500/5',
    Archive: 'border-zinc-600/40 bg-zinc-600/5',
  }

  const barColors: Record<string, string> = {
    Inbox: 'bg-neutral',
    Processing: 'bg-warning',
    Library: 'bg-success',
    Campaigns: 'bg-primary',
    Assets: 'bg-purple-500',
    Archive: 'bg-zinc-600',
  }

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={GitBranch}
        title="Pipeline"
        subtitle="Stage counts, visual flow, and folder ownership"
      />

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Library Size</div>
          <div className="text-3xl font-mono font-semibold text-success">{pipeline.librarySize}</div>
          <div className="text-xs text-zinc-500 mt-1">approved entities</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Pending Review</div>
          <div className="text-3xl font-mono font-semibold text-warning">{pipeline.pendingReview}</div>
          <div className="text-xs text-zinc-500 mt-1">in 01-Processing</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 uppercase tracking-wide mb-1">Throughput (done)</div>
          <div className="text-3xl font-mono font-semibold text-primary">{pipeline.throughput24h}</div>
          <div className="text-xs text-zinc-500 mt-1">queue items completed</div>
        </div>
      </div>

      {/* Visual flow */}
      <div className="panel p-6 mb-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-5">Flow</div>
        <div className="flex items-stretch gap-1 flex-wrap">
          {pipeline.stages.map((stage, i) => (
            <div key={stage.name} className="flex items-center gap-1 flex-1 min-w-[120px]">
              <div className={`flex-1 rounded-lg border p-4 ${stageColors[stage.name] ?? 'border-surface-3 bg-surface-2'}`}>
                <div className="text-lg font-mono font-bold text-zinc-100">{stage.count}</div>
                <div className="text-sm font-medium text-zinc-200">{stage.name}</div>
                <div className="text-xs text-zinc-500 mt-1">{stage.folder}</div>
                <div className="text-[10px] text-zinc-600 mt-1">owner: {stage.owner}</div>
                <div className="mt-2 h-1 bg-surface-3 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${barColors[stage.name] ?? 'bg-zinc-600'} rounded-full`}
                    style={{ width: `${Math.min(100, (stage.count / total) * 100 * 3)}%` }}
                  />
                </div>
              </div>
              {i < pipeline.stages.length - 1 && (
                <ArrowRight size={14} className="text-zinc-600 flex-shrink-0" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Workflow steps */}
      <div className="panel p-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-4">Workflow</div>
        <div className="space-y-3">
          {[
            { step: '1', desc: 'Drop sources into 00-Inbox — treat as read-only', status: 'manual' },
            { step: '2', desc: 'Automation agents process 00-Inbox and write drafts to 01-Processing', status: 'auto' },
            { step: '3', desc: 'Human reviews drafts, sets status: approved + quality: N', status: 'manual' },
            { step: '4', desc: 'Approved content promoted to 02-Library (or 03-Campaigns, 05-Assets)', status: 'auto' },
            { step: '5', desc: 'Relationships auto-indexed into 04-Relationships', status: 'auto' },
          ].map(({ step, desc, status }) => (
            <div key={step} className="flex items-start gap-3">
              <div className="w-6 h-6 rounded-full bg-surface-3 flex items-center justify-center text-xs font-mono text-zinc-400 flex-shrink-0">
                {step}
              </div>
              <div className="flex-1">
                <span className="text-sm text-zinc-300">{desc}</span>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded font-mono ${
                status === 'auto' ? 'bg-primary/10 text-primary' : 'bg-warning/10 text-warning'
              }`}>
                {status}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
