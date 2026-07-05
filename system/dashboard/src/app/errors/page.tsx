export const dynamic = 'force-dynamic'

import { readLogs, readAllReports, readLatestReport } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import ActivityFeed from '@/components/widgets/ActivityFeed'
import RepairAgentButton from '@/components/widgets/RepairAgentButton'
import { Zap } from 'lucide-react'
import type { LogLine } from '@/lib/types'

export default async function ErrorsPage() {
  const [allLogs, reports, latestReport] = await Promise.all([
    Promise.resolve(readLogs({ limit: 500 })),
    Promise.resolve(readAllReports()),
    Promise.resolve(readLatestReport()),
  ])

  const errorLogs = allLogs.filter((l) => l.severity === 'ERROR')
  const warnLogs = allLogs.filter((l) => l.severity === 'WARN')

  // Group errors by task
  const byTask: Record<string, LogLine[]> = {}
  for (const log of errorLogs) {
    if (!byTask[log.task]) byTask[log.task] = []
    byTask[log.task].push(log)
  }

  // Report breakdown
  const reportEntries = Object.entries(reports).sort(([a], [b]) => b.localeCompare(a))
  const totalReportErrors = latestReport
    ? Object.values(latestReport.agentSummaries).reduce((s, a) => s + a.errors, 0)
    : 0
  const totalReportWarns = latestReport
    ? Object.values(latestReport.agentSummaries).reduce((s, a) => s + a.warnings, 0)
    : 0

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Zap}
        title="Error Monitoring"
        subtitle="Grouped errors and daily report breakdown"
      />

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Log Errors</div>
          <div className={`text-3xl font-mono font-semibold ${errorLogs.length > 0 ? 'text-danger' : 'text-success'}`}>
            {errorLogs.length}
          </div>
          <div className="text-xs text-zinc-500 mt-1">in log tail</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Log Warnings</div>
          <div className={`text-3xl font-mono font-semibold ${warnLogs.length > 0 ? 'text-warning' : 'text-zinc-400'}`}>
            {warnLogs.length}
          </div>
          <div className="text-xs text-zinc-500 mt-1">in log tail</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Report Errors</div>
          <div className={`text-3xl font-mono font-semibold ${totalReportErrors > 0 ? 'text-danger' : 'text-success'}`}>
            {totalReportErrors}
          </div>
          <div className="text-xs text-zinc-500 mt-1">today&apos;s report</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Report Warns</div>
          <div className={`text-3xl font-mono font-semibold ${totalReportWarns > 0 ? 'text-warning' : 'text-zinc-400'}`}>
            {totalReportWarns}
          </div>
          <div className="text-xs text-zinc-500 mt-1">today&apos;s report</div>
        </div>
      </div>

      {/* Errors by task */}
      {Object.keys(byTask).length > 0 && (
        <div className="panel mb-6 overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="text-sm font-semibold text-danger">Errors by Agent</div>
          </div>
          <div className="divide-y divide-surface-3">
            {Object.entries(byTask)
              .sort(([, a], [, b]) => b.length - a.length)
              .map(([task, logs]) => (
                <div key={task} className="px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-sm text-danger">[{task}]</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs px-2 py-0.5 rounded bg-danger/10 text-danger font-mono">
                        {logs.length} error{logs.length !== 1 ? 's' : ''}
                      </span>
                      <RepairAgentButton agent={task} error={logs[0]?.message ?? ''} />
                    </div>
                  </div>
                  <div className="space-y-1">
                    {logs.slice(0, 3).map((log, i) => (
                      <div key={i} className="text-xs font-mono text-zinc-400 flex gap-2">
                        <span className="text-zinc-600">{log.timestamp.slice(11, 19)}</span>
                        <span className="text-danger/80 flex-1">{log.message}</span>
                      </div>
                    ))}
                    {logs.length > 3 && (
                      <div className="text-xs text-zinc-600 font-mono">... and {logs.length - 3} more</div>
                    )}
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Daily report breakdown */}
      {latestReport && (
        <div className="panel mb-6 overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="text-sm font-semibold text-zinc-200">
              Today&apos;s Report — {latestReport.date}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-3 text-zinc-500">
                  <th className="px-4 py-2 text-left">Agent</th>
                  <th className="px-4 py-2 text-right">Runs</th>
                  <th className="px-4 py-2 text-right">Completed</th>
                  <th className="px-4 py-2 text-right">Errors</th>
                  <th className="px-4 py-2 text-right">Warnings</th>
                  <th className="px-4 py-2 text-left">Last Run</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(latestReport.agentSummaries)
                  .sort(([, a], [, b]) => b.errors - a.errors)
                  .map(([agent, summary]) => (
                    <tr key={agent} className="border-b border-surface-3/50 hover:bg-surface-2">
                      <td className="px-4 py-2 font-mono text-zinc-300">{agent}</td>
                      <td className="px-4 py-2 font-mono text-zinc-400 text-right">{summary.runs}</td>
                      <td className="px-4 py-2 font-mono text-success text-right">{summary.completedRuns}</td>
                      <td className={`px-4 py-2 font-mono text-right ${summary.errors > 0 ? 'text-danger' : 'text-zinc-500'}`}>
                        {summary.errors}
                      </td>
                      <td className={`px-4 py-2 font-mono text-right ${summary.warnings > 0 ? 'text-warning' : 'text-zinc-500'}`}>
                        {summary.warnings}
                      </td>
                      <td className="px-4 py-2 text-zinc-500">{summary.lastRun}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Historical reports */}
      {reportEntries.length > 1 && (
        <div className="panel mb-6 overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="text-sm font-semibold text-zinc-200">Historical Reports</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-3 text-zinc-500">
                  <th className="px-4 py-2 text-left">Date</th>
                  <th className="px-4 py-2 text-right">Total Runs</th>
                  <th className="px-4 py-2 text-right">Errors</th>
                  <th className="px-4 py-2 text-right">Warnings</th>
                </tr>
              </thead>
              <tbody>
                {reportEntries.map(([date, report]) => {
                  const totalRuns = Object.values(report.agentSummaries).reduce((s, a) => s + a.runs, 0)
                  const totalErrors = Object.values(report.agentSummaries).reduce((s, a) => s + a.errors, 0)
                  const totalWarnings = Object.values(report.agentSummaries).reduce((s, a) => s + a.warnings, 0)
                  return (
                    <tr key={date} className="border-b border-surface-3/50 hover:bg-surface-2">
                      <td className="px-4 py-2 font-mono text-zinc-300">{date}</td>
                      <td className="px-4 py-2 font-mono text-zinc-400 text-right">{totalRuns}</td>
                      <td className={`px-4 py-2 font-mono text-right ${totalErrors > 0 ? 'text-danger' : 'text-zinc-500'}`}>
                        {totalErrors}
                      </td>
                      <td className={`px-4 py-2 font-mono text-right ${totalWarnings > 0 ? 'text-warning' : 'text-zinc-500'}`}>
                        {totalWarnings}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Error log feed */}
      <div className="panel overflow-hidden">
        <div className="px-4 py-3 border-b border-surface-3">
          <div className="text-sm font-semibold text-zinc-200">Error Log</div>
        </div>
        {errorLogs.length === 0 ? (
          <div className="p-8 text-center text-success text-sm">No errors in log tail</div>
        ) : (
          <ActivityFeed logs={errorLogs} maxHeight="400px" />
        )}
      </div>
    </div>
  )
}
