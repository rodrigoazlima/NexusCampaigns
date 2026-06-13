import { PageHeader } from '@/components/widgets/PageHeader'
import { cn, fmtDate } from '@/lib/utils'
import { parseLog, latestReport } from '@/lib/vault'
import type { LogLine, DailyReport } from '@/lib/types'
import { AutoRefresh } from '@/components/AutoRefresh'

export const dynamic = 'force-dynamic'

export default function ErrorsPage() {
  const errors = parseLog(600).filter(l => l.severity === 'error').slice(0, 200)
  const report = latestReport() as DailyReport | null

  // Group errors by agent
  const byAgent: Record<string, LogLine[]> = {}
  for (const e of errors) {
    if (!byAgent[e.taskId]) byAgent[e.taskId] = []
    byAgent[e.taskId].push(e)
  }

  const agentsSorted = Object.entries(byAgent).sort((a, b) => b[1].length - a[1].length)

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader title="Error Monitoring" icon="⚡" subtitle="Agent failures, conversion errors, blocked queue items" />

      <div className="p-6 space-y-6">

        {/* Summary */}
        <div className="grid grid-cols-3 gap-3">
          <div className="card p-4 text-center border-t-2 border-t-danger/60">
            <div className={cn('text-2xl font-semibold tabular-nums', errors.length > 0 ? 'text-danger' : 'text-success')}>{errors.length}</div>
            <div className="text-xs text-neutral mt-1">Total Errors (log tail)</div>
          </div>
          <div className="card p-4 text-center">
            <div className="text-2xl font-semibold tabular-nums text-warning">{Object.keys(byAgent).length}</div>
            <div className="text-xs text-neutral mt-1">Agents with Errors</div>
          </div>
          <div className="card p-4 text-center">
            <div className={cn('text-2xl font-semibold tabular-nums', report && report.summary.totalErrors > 0 ? 'text-danger' : 'text-success')}>
              {report?.summary.totalErrors ?? '—'}
            </div>
            <div className="text-xs text-neutral mt-1">Errors (last 24h report)</div>
          </div>
        </div>

        {/* Per-agent error breakdown from report */}
        {report && Object.keys(report.tasks).length > 0 && (
          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-3">
              <div className="section-title">24h Report — Agent Breakdown</div>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-3 text-left">
                  <Th>Agent</Th><Th>Runs</Th><Th>Completed</Th><Th>Errors</Th><Th>Warnings</Th><Th>Last Run</Th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(report.tasks).map(([id, task]) => (
                  <tr key={id} className="table-row-hover border-b border-surface-3/50">
                    <td className="px-4 py-2.5 font-medium text-white">{id}</td>
                    <td className="px-4 py-2.5 tabular-nums text-neutral">{task.runs}</td>
                    <td className="px-4 py-2.5 tabular-nums text-success">{task.completedRuns}</td>
                    <td className="px-4 py-2.5 tabular-nums">
                      <span className={task.errors.length > 0 ? 'text-danger font-medium' : 'text-neutral'}>{task.errors.length}</span>
                    </td>
                    <td className="px-4 py-2.5 tabular-nums">
                      <span className={task.warnings.length > 0 ? 'text-warning' : 'text-neutral'}>{task.warnings.length}</span>
                    </td>
                    <td className="px-4 py-2.5 text-neutral text-xs">{fmtDate(task.lastRun)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Per-agent error list */}
        {agentsSorted.map(([agentId, agentErrors]) => (
          <div key={agentId} className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-danger/20 flex items-center justify-between bg-danger/5">
              <div className="flex items-center gap-2">
                <span className="dot-error" />
                <div className="section-title text-danger">{agentId}</div>
              </div>
              <span className="text-xs text-danger font-medium">{agentErrors.length} error{agentErrors.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-surface-3 text-left">
                    <th className="px-4 py-2 text-neutral font-medium">Timestamp</th>
                    <th className="px-4 py-2 text-neutral font-medium">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {agentErrors.slice(0, 20).map((e, i) => (
                    <tr key={i} className="table-row-hover border-b border-surface-3/50">
                      <td className="px-4 py-1.5 text-neutral whitespace-nowrap">{fmtDate(e.timestamp, 'MM-dd HH:mm:ss')}</td>
                      <td className="px-4 py-1.5 text-danger max-w-2xl">{e.message}</td>
                    </tr>
                  ))}
                  {agentErrors.length > 20 && (
                    <tr><td colSpan={2} className="px-4 py-2 text-neutral text-center">… and {agentErrors.length - 20} more</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ))}

        {errors.length === 0 && (
          <div className="card p-12 text-center">
            <div className="text-4xl mb-3">✅</div>
            <div className="text-white font-medium">No errors in log tail</div>
            <div className="text-sm text-neutral mt-1">All agents are running cleanly</div>
          </div>
        )}

      </div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-xs font-medium text-neutral uppercase tracking-wide">{children}</th>
}
