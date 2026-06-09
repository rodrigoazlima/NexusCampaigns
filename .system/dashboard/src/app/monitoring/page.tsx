import { PageHeader } from '@/components/widgets/PageHeader'
import { AutoRefresh } from '@/components/AutoRefresh'
import { getAgentInfo, latestReport, latestRepairReport, readAgentMetrics } from '@/lib/vault'
import { statusBadge, cn } from '@/lib/utils'
import type { DailyReport, AgentStatus } from '@/lib/types'

export const dynamic = 'force-dynamic'

function itemType(name: string): 'npc' | 'battlemap' | 'scene' | 'other' {
  if (/^(npc|human|elf|dwarf|orc|goblin|undead|devil|dark-elf|dragon|ogre)/.test(name)) return 'npc'
  if (/^battlemap/.test(name)) return 'battlemap'
  if (/^scene/.test(name)) return 'scene'
  return 'other'
}

const TYPE_DOT_CLASS: Record<string, string> = {
  npc:       'bg-blue-400',
  battlemap: 'bg-violet-400',
  scene:     'bg-emerald-400',
  other:     'bg-zinc-500',
}

const AGENT_BORDER: Record<AgentStatus, string> = {
  idle:    'border-t-success/60',
  running: 'border-t-success',
  error:   'border-t-danger',
  offline: 'border-t-zinc-600',
}

function fmtMs(ms: number | null): string {
  if (ms === null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export default function MonitoringPage() {
  const agents  = getAgentInfo()
  const report  = latestReport() as DailyReport | null
  const repair  = latestRepairReport()
  const metrics = readAgentMetrics()

  const summary     = report?.summary
  const health      = report?.vaultHealth
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const queueStats  = (report as any)?.queueStats as { total: number; pending: number; done: number; stuck: number } | null

  const totalRuns     = summary?.totalRuns     ?? 0
  const totalErrors   = summary?.totalErrors   ?? 0
  const totalWarnings = summary?.totalWarnings ?? 0
  const pending       = health?.pendingReview  ?? []
  const orphans       = health?.orphans        ?? []

  // quality buckets from report's qualitySuggestions
  const qualSugg = health?.qualitySuggestions ?? {}
  const qBuckets = { low: 0, needs: 0, good: 0, library: 0 }
  for (const q of Object.values(qualSugg)) {
    if (q <= 3)      qBuckets.low++
    else if (q <= 6) qBuckets.needs++
    else if (q <= 8) qBuckets.good++
    else             qBuckets.library++
  }
  const qTotal = Object.values(qBuckets).reduce((a, b) => a + b, 0)

  // error buckets from latest repair report
  const errorBuckets: Record<string, number> = (repair?.errorBuckets as Record<string, number>) ?? {}
  const ebKeys = Object.keys(errorBuckets)
  const ebMax  = Math.max(...Object.values(errorBuckets), 1)

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader
        title="Monitoring"
        icon="📡"
        subtitle={`${report?.date ?? 'no report'} · ${agents.length} agents`}
      />

      <div className="p-6 space-y-6">

        {/* ── Stat cards ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {([
            { label: 'Runs (24h)',      value: totalRuns,     cls: 'text-blue-400' },
            { label: 'Errors',          value: totalErrors,   cls: totalErrors   > 0 ? 'text-danger'  : 'text-success' },
            { label: 'Warnings',        value: totalWarnings, cls: totalWarnings > 0 ? 'text-warning' : 'text-success' },
            { label: 'Pending Review',  value: pending.length, cls: 'text-success' },
          ] as const).map(s => (
            <div key={s.label} className="card p-4">
              <div className={`text-3xl font-bold tabular-nums tracking-tight ${s.cls}`}>{s.value}</div>
              <div className="section-title mt-1">{s.label}</div>
            </div>
          ))}
        </div>

        {/* ── Queue stats ── */}
        {queueStats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {([
              { label: 'Queue Total',   value: queueStats.total,   cls: 'text-neutral-light' },
              { label: 'Queue Pending', value: queueStats.pending, cls: queueStats.pending > 0 ? 'text-warning' : 'text-success' },
              { label: 'Queue Done',    value: queueStats.done,    cls: 'text-success' },
              { label: 'Stuck (>48h)', value: queueStats.stuck,   cls: queueStats.stuck > 0 ? 'text-danger' : 'text-success' },
            ] as const).map(s => (
              <div key={s.label} className="card p-4">
                <div className={`text-3xl font-bold tabular-nums tracking-tight ${s.cls}`}>{s.value}</div>
                <div className="section-title mt-1">{s.label}</div>
              </div>
            ))}
          </div>
        )}

        {/* ── Agents ── */}
        <div>
          <div className="section-title mb-3">Agents</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
            {agents.map(agent => {
              const mins = agent.lastRun
                ? Math.round((Date.now() - new Date(agent.lastRun).getTime()) / 60_000)
                : null
              const shortName = agent.id.replace('-agent', '')
              const desc = agent.description.replace(/^[^:]+:\s*/, '').slice(0, 50)
              return (
                <div
                  key={agent.id}
                  className={cn('card p-3.5 border-t-2', AGENT_BORDER[agent.status])}
                >
                  <div className="font-semibold text-sm text-white mb-0.5 truncate">{shortName}</div>
                  <div className="text-[11px] text-neutral truncate mb-2.5">{desc}</div>
                  <div className="flex items-center justify-between gap-1">
                    <span className={cn('badge text-[10px]', statusBadge(agent.status))}>{agent.status}</span>
                    <span className="text-[10px] font-mono text-neutral shrink-0">
                      {mins !== null ? `${mins}m ago` : '—'}
                    </span>
                  </div>
                  <div className="text-[10px] text-neutral/60 mt-1.5">
                    {agent.intervalSeconds >= 3600
                      ? `${agent.intervalSeconds / 3600}h`
                      : `${agent.intervalSeconds / 60}m`}
                    {' · runs: '}{agent.runs24h}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Agent performance ── */}
        {Object.keys(metrics).length > 0 && (
          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-surface-3">
              <div className="section-title">Agent Performance (last 20 runs)</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-neutral border-b border-surface-3">
                    <th className="text-left px-4 py-2 font-medium">Agent</th>
                    <th className="text-right px-4 py-2 font-medium">Runs</th>
                    <th className="text-right px-4 py-2 font-medium">Avg Duration</th>
                    <th className="text-right px-4 py-2 font-medium">Items/Run</th>
                    <th className="text-right px-4 py-2 font-medium">Failed/Run</th>
                    <th className="text-right px-4 py-2 font-medium">Last Run</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map(agent => {
                    const m = metrics[agent.id]
                    const runs = m?.runs ?? []
                    const runCount = runs.length
                    const slice = runs.slice(0, 20)
                    const avgDur = runCount > 0
                      ? Math.round(slice.reduce((a, r) => a + (r.durationMs ?? 0), 0) / slice.length)
                      : null
                    const avgItems = runCount > 0
                      ? (slice.reduce((a, r) => a + (r.itemsProcessed ?? 0), 0) / slice.length).toFixed(1)
                      : '—'
                    const avgFailed = runCount > 0
                      ? (slice.reduce((a, r) => a + (r.itemsFailed ?? 0), 0) / slice.length).toFixed(1)
                      : '—'
                    const lastRun = runs[0]?.startedAt
                      ? new Date(runs[0].startedAt).toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit' })
                      : '—'
                    return (
                      <tr key={agent.id} className="border-b border-surface-3/50 hover:bg-surface-3/30">
                        <td className="px-4 py-2 font-mono text-neutral-light">{agent.id.replace('-agent', '')}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-neutral">{runCount}</td>
                        <td className="px-4 py-2 text-right tabular-nums font-mono text-blue-400">{fmtMs(avgDur)}</td>
                        <td className="px-4 py-2 text-right tabular-nums text-success">{avgItems}</td>
                        <td className={cn('px-4 py-2 text-right tabular-nums',
                          avgFailed !== '—' && parseFloat(avgFailed as string) > 0 ? 'text-danger' : 'text-neutral'
                        )}>{avgFailed}</td>
                        <td className="px-4 py-2 text-right font-mono text-neutral">{lastRun}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Error buckets + Quality ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

          <div className="card p-4">
            <div className="section-title mb-4">Error Buckets (24h)</div>
            {ebKeys.length === 0 ? (
              <p className="text-xs text-neutral">No error buckets recorded.</p>
            ) : (
              <div className="space-y-3">
                {ebKeys.map(key => {
                  const val = errorBuckets[key]
                  const pct = Math.max(4, (val / ebMax) * 100)
                  const barCls = key.includes('offline') ? 'bg-danger'
                    : key.includes('reload')  ? 'bg-[#8b5cf6]'
                    : 'bg-warning'
                  return (
                    <div key={key} className="flex items-center gap-2.5">
                      <span className="text-xs font-mono text-neutral-light min-w-[160px] truncate">{key}</span>
                      <div className="flex-1 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                        <div className={cn('h-full rounded-full', barCls)} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-xs font-mono text-neutral min-w-[24px] text-right">{val}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div className="card p-4">
            <div className="section-title mb-4">Quality Distribution</div>
            <div className="space-y-2.5">
              {([
                { label: 'Low (0–3)',      value: qBuckets.low,     cls: 'bg-danger' },
                { label: 'Review (4–6)',   value: qBuckets.needs,   cls: 'bg-warning' },
                { label: 'Good (7–8)',     value: qBuckets.good,    cls: 'bg-primary' },
                { label: 'Library (9–10)', value: qBuckets.library, cls: 'bg-success' },
              ] as const).map(row => {
                const pct = qTotal > 0 ? Math.max(2, (row.value / qTotal) * 100) : 0
                return (
                  <div key={row.label} className="flex items-center gap-2.5">
                    <span className="text-xs text-neutral-light min-w-[110px]">{row.label}</span>
                    <div className="flex-1 h-2 bg-surface-3 rounded-full overflow-hidden">
                      <div className={cn('h-full rounded-full', row.cls)} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs font-mono text-neutral min-w-[28px] text-right">{row.value}</span>
                  </div>
                )
              })}
            </div>
            <div className="text-[11px] text-neutral mt-4">
              {qTotal} files scored · {qBuckets.library} library-ready
            </div>
          </div>

        </div>

        {/* ── Orphans ── */}
        {orphans.length > 0 && (
          <div className="card p-4">
            <div className="section-title mb-3">Orphan Files ({orphans.length})</div>
            <div className="flex flex-wrap gap-2">
              {orphans.map(o => (
                <span
                  key={o}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-danger/10 border border-danger/20 text-danger text-[11px] font-mono"
                >
                  ⚠ {o.replace(/^01-Processing[/\\]/, '').replace('.md', '')}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* ── Pending review ── */}
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between">
            <div className="section-title">Pending Review</div>
            <span className="text-[11px] font-semibold text-warning bg-warning/10 border border-warning/20 px-2 py-0.5 rounded-full">
              {pending.length} files
            </span>
          </div>
          {pending.length === 0 ? (
            <div className="p-8 text-center text-neutral text-sm">No items pending review</div>
          ) : (
            <div className="p-4 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-1.5 max-h-64 overflow-y-auto">
              {pending.map(p => {
                const name = p.replace(/^01-Processing[/\\]/, '').replace('.md', '')
                const type = itemType(name)
                return (
                  <div
                    key={p}
                    className="flex items-center gap-1.5 px-2 py-1.5 rounded bg-surface-3 text-[11px] font-mono text-neutral-light overflow-hidden"
                  >
                    <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', TYPE_DOT_CLASS[type])} />
                    <span className="truncate" title={name}>{name}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
