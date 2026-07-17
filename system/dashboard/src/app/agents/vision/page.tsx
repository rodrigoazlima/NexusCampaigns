export const dynamic = 'force-dynamic'

import Link from 'next/link'
import { Eye } from 'lucide-react'
import {
  readAgents,
  readAgentDoc,
  readAgentConfig,
  readQueue,
  readVisionState,
  readLogs,
} from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import StatusBadge from '@/components/widgets/StatusBadge'
import ActivityFeed from '@/components/widgets/ActivityFeed'
import AutoRefresh from '@/components/AutoRefresh'
import { AgentConfigButton } from '@/components/agents/AgentConfigButton'
import AgentQueueTable from '@/components/queue/AgentQueueTable'
import { formatDateTime, formatDuration, formatRelative } from '@/lib/utils'
import type { VisionImageRecord } from '@/lib/types'

export default async function VisionAgentPage() {
  const agent = readAgents().find((a) => a.name === 'vision')

  if (!agent) {
    return <div className="p-6 text-sm text-zinc-500">Vision agent not found in registry.</div>
  }

  const doc = readAgentDoc('vision')
  const config = readAgentConfig('vision')
  const taskConfig = config?.tasks[agent.id]
  const cli = taskConfig?.dispatch.type === 'cli' ? taskConfig.dispatch.cli : null

  const queueItems = readQueue().items.filter((i) => 'vision' in i.agents)
  const byType: Record<string, number> = {}
  for (const item of queueItems) {
    byType[item.type] = (byType[item.type] ?? 0) + 1
  }

  const images = Object.values(readVisionState()) as unknown as VisionImageRecord[]
  const typeCounts: Record<string, number> = {}
  let okCount = 0
  let failedCount = 0
  for (const img of images) {
    typeCounts[img.type] = (typeCounts[img.type] ?? 0) + 1
    if (img.status === 'ok') okCount++
    else if (img.status === 'failed') failedCount++
  }
  const recentImages = [...images]
    .sort((a, b) => (b.processedAt ?? '').localeCompare(a.processedAt ?? ''))
    .slice(0, 30)

  const logs = readLogs({ task: agent.id, limit: 150 })

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Eye}
        title="Vision Agent"
        subtitle={doc?.purpose || agent.description}
        actions={<AgentConfigButton agent={agent} />}
      />

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Status</div>
          <StatusBadge status={agent.status} />
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Runs</div>
          <div className="text-2xl font-mono font-semibold text-zinc-100">{agent.totalRuns}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Processed</div>
          <div className="text-2xl font-mono font-semibold text-zinc-100">{agent.totalProcessed}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Failed</div>
          <div className={`text-2xl font-mono font-semibold ${agent.totalFailed > 0 ? 'text-danger' : 'text-zinc-100'}`}>
            {agent.totalFailed}
          </div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Avg Duration</div>
          <div className="text-2xl font-mono font-semibold text-zinc-100">
            {agent.avgDurationMs > 0 ? formatDuration(agent.avgDurationMs) : '-'}
          </div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Last Run</div>
          <div className="text-sm font-mono text-zinc-300 mt-1.5" suppressHydrationWarning>{formatRelative(agent.lastRun)}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Configuration */}
        <div className="panel p-4 lg:col-span-2">
          <div className="text-sm font-semibold text-zinc-200 mb-3">Configuration</div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="text-zinc-500">Task ID</dt>
              <dd className="font-mono text-zinc-300">{agent.id}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-zinc-500">Interval</dt>
              <dd className="font-mono text-zinc-300">{agent.intervalSeconds}s ({agent.intervalSeconds / 60}m)</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-zinc-500">Dispatch</dt>
              <dd className="font-mono text-zinc-300">{agent.intelligence}</dd>
            </div>
            {cli && (
              <>
                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500 shrink-0">Command</dt>
                  <dd className="font-mono text-zinc-300 text-right break-all">{cli.command} {cli.args?.join(' ')}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Timeout</dt>
                  <dd className="font-mono text-zinc-300">{cli.timeout_seconds ?? '-'}s</dd>
                </div>
              </>
            )}
            <div className="flex justify-between gap-3">
              <dt className="text-zinc-500 shrink-0">LLM Endpoint</dt>
              <dd className="font-mono text-zinc-300 text-right">localhost:1234 · qwen3-vl-4b-instruct</dd>
            </div>
            {doc && doc.dependencies.length > 0 && (
              <div className="flex justify-between gap-3">
                <dt className="text-zinc-500">Dependencies</dt>
                <dd className="font-mono text-zinc-300">{doc.dependencies.join(', ')}</dd>
              </div>
            )}
          </dl>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 mt-4">
            {doc && doc.responsibilities.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 mb-1.5">Responsibilities</div>
                <ul className="space-y-1 text-xs text-zinc-400 list-disc list-inside">
                  {doc.responsibilities.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}

            {doc && doc.restrictions.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 mb-1.5">Restrictions</div>
                <ul className="space-y-1 text-xs text-zinc-400 list-disc list-inside">
                  {doc.restrictions.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>

        {/* State files */}
        <div className="panel p-4">
          <div className="text-sm font-semibold text-zinc-200 mb-3">State Files</div>
          {doc && doc.state_files.length > 0 ? (
            <ul className="space-y-1.5 text-xs font-mono text-zinc-400 break-all">
              {doc.state_files.map((f) => <li key={f}>{f}</li>)}
            </ul>
          ) : (
            <p className="text-xs text-zinc-600">-</p>
          )}
        </div>
      </div>

      {/* Queue items - vision-slot status only, with pause/continue/reprocess/delete actions */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold text-zinc-200">Queue Items - vision step</div>
          <Link href="/queue" className="text-xs text-primary hover:underline">Full queue →</Link>
        </div>
        <AgentQueueTable items={queueItems} agent="vision" byType={byType} />
      </div>

      {/* Processed images */}
      <div className="panel mb-6 overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between flex-wrap gap-2">
          <div className="text-sm font-semibold text-zinc-200">Processed Images ({images.length})</div>
          <div className="flex gap-3 text-xs">
            <span className="text-success">{okCount} ok</span>
            <span className="text-danger">{failedCount} failed</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 px-4 py-3 border-b border-surface-3/50">
          {Object.entries(typeCounts).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
            <span key={type} className="px-2 py-1 bg-surface-2 rounded text-xs font-mono text-zinc-300">
              {type} <span className="text-zinc-500">{count}</span>
            </span>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-surface-3 text-zinc-500">
                <th className="px-4 py-2 text-left">File</th>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">Ancestry / Class</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-right">Processed</th>
              </tr>
            </thead>
            <tbody>
              {recentImages.map((img) => (
                <tr key={img.path} className="border-b border-surface-3/50 hover:bg-surface-2">
                  <td className="px-4 py-2 font-mono text-zinc-300 truncate max-w-[280px]" title={img.path}>
                    {img.originalName || img.path.split('/').pop()}
                  </td>
                  <td className="px-4 py-2 text-zinc-400">{img.type}</td>
                  <td className="px-4 py-2 text-zinc-500">
                    {[img.ancestry, img.class].filter((v) => v && v !== 'none').join(' · ') || '-'}
                  </td>
                  <td className="px-4 py-2">
                    <span className={img.status === 'ok' ? 'text-success' : 'text-danger'}>{img.status}</span>
                  </td>
                  <td className="px-4 py-2 font-mono text-zinc-500 text-right">{formatDateTime(img.processedAt)}</td>
                </tr>
              ))}
              {recentImages.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-zinc-600">No images processed yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Live log */}
      <div className="panel overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-3">
          <div className="text-sm font-semibold text-zinc-200">Latest Logs</div>
        </div>
        <ActivityFeed logs={logs} maxHeight="400px" />
      </div>
    </div>
  )
}
