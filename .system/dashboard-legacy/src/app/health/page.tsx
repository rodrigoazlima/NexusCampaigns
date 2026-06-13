'use client'

import { useState, useEffect } from 'react'
import { PageHeader } from '@/components/widgets/PageHeader'
import { AutoRefresh } from '@/components/AutoRefresh'
import type { DailyReport } from '@/lib/types'

// ── Types ──────────────────────────────────────────────────────────────────

interface TaskCfg {
  id: string
  script: string
  intervalSeconds: number
  description: string
}

interface AllReportsResponse {
  reports: Record<string, DailyReport>
  tasks: TaskCfg[]
}

interface AggTask {
  runs: number
  completedRuns: number
  errors: Array<{ timestamp: string; message: string }>
  warnings: Array<{ timestamp: string; message: string }>
  firstRun: number | null
  lastRun: number | null
}

type SlotStatus = 'ok' | 'err' | 'wrn' | 'both' | 'none'

interface Slot {
  slotStart: number
  slotEnd: number
  errors: Array<{ timestamp: string; message: string }>
  warnings: Array<{ timestamp: string; message: string }>
  status: SlotStatus
  active: boolean
}

interface SlotMeta {
  slots: Slot[]
  intervalMs: number
  expectedTotal: number
  actualTotal: number
  completedTotal: number
}

interface ModalState {
  taskName: string
  dateLbl: string
  range: string
  slot: Slot
  meta: SlotMeta
}

// ── Constants ──────────────────────────────────────────────────────────────

const PERIODS = [
  { label: '1h',   ms: 3_600_000 },
  { label: '4h',   ms: 14_400_000 },
  { label: '12h',  ms: 43_200_000 },
  { label: '24h',  ms: 86_400_000 },
  { label: '7d',   ms: 604_800_000 },
  { label: '30d',  ms: 2_592_000_000 },
  { label: '90d',  ms: 7_776_000_000 },
  { label: '180d', ms: 15_552_000_000 },
  { label: '1y',   ms: 31_536_000_000 },
  { label: 'All',  ms: null },
] as const

const MAX_BARS = 120

const STATUS_COLOR: Record<SlotStatus, string> = {
  ok:   '#10b981',
  err:  '#ef4444',
  wrn:  '#f59e0b',
  both: '#f97316',
  none: '#27272a',
}

const STATUS_LABEL: Record<SlotStatus, string> = {
  ok:   'Clean — no issues',
  err:  'Errors detected',
  wrn:  'Warnings detected',
  both: 'Errors + Warnings',
  none: 'No run in this slot',
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtTime(iso: string) {
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) }
  catch { return iso }
}

function fmtDT(iso: string) {
  try { return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) }
  catch { return iso }
}

function fmtDateShort(ms: number) {
  return new Date(ms).toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function getViewRange(reports: Record<string, DailyReport>, pidx: number) {
  const p = PERIODS[pidx]
  const endMs = Date.now()
  if (p.ms === null) {
    const sorted = Object.keys(reports).sort()
    const startMs = sorted.length
      ? new Date(sorted[0].replace(/-/g, '/')).getTime()
      : endMs - 7 * 86_400_000
    return { startMs, endMs }
  }
  return { startMs: endMs - p.ms, endMs }
}

function allTaskIds(reports: Record<string, DailyReport>) {
  const ids = new Set<string>()
  Object.values(reports).forEach(r => r.tasks && Object.keys(r.tasks).forEach(id => ids.add(id)))
  return [...ids].sort()
}

function aggregateTask(
  reports: Record<string, DailyReport>,
  taskId: string,
  startMs: number,
  endMs: number,
): AggTask {
  const result: AggTask = { runs: 0, completedRuns: 0, errors: [], warnings: [], firstRun: null, lastRun: null }
  Object.values(reports).forEach(r => {
    if (!r?.tasks?.[taskId]) return
    const pS = new Date(r.periodStart).getTime()
    const pE = new Date(r.periodEnd).getTime()
    if (pE < startMs || pS > endMs) return
    const t = r.tasks[taskId]
    result.runs += t.runs || 0
    result.completedRuns += t.completedRuns || 0
    ;(t.errors || []).forEach(e => {
      const ts = new Date(e.timestamp).getTime()
      if (ts >= startMs && ts <= endMs) result.errors.push(e)
    })
    ;(t.warnings || []).forEach(w => {
      const ts = new Date(w.timestamp).getTime()
      if (ts >= startMs && ts <= endMs) result.warnings.push(w)
    })
    if (t.firstRun) {
      const fr = new Date(t.firstRun).getTime()
      if (result.firstRun === null || fr < result.firstRun) result.firstRun = fr
    }
    if (t.lastRun) {
      const lr = new Date(t.lastRun).getTime()
      if (result.lastRun === null || lr > result.lastRun) result.lastRun = lr
    }
  })
  return result
}

function buildSlots(task: AggTask, startMs: number, endMs: number, intervalSec: number): SlotMeta {
  const intervalMs = intervalSec * 1000
  const periodMs = endMs - startMs
  const rawSlotMs = Math.max(intervalMs, periodMs / MAX_BARS)
  const slotMs = Math.ceil(rawSlotMs / intervalMs) * intervalMs
  const N = Math.max(1, Math.round(periodMs / slotMs))
  const slots: Slot[] = []
  for (let i = 0; i < N; i++) {
    const sS = startMs + i * slotMs
    const sE = sS + slotMs
    const active =
      task.firstRun !== null &&
      task.lastRun !== null &&
      sE > task.firstRun &&
      sS <= task.lastRun + slotMs
    const errs = task.errors.filter(e => { const t = new Date(e.timestamp).getTime(); return t >= sS && t < sE })
    const wrns = task.warnings.filter(w => { const t = new Date(w.timestamp).getTime(); return t >= sS && t < sE })
    let status: SlotStatus = 'none'
    if (active) {
      if (errs.length && wrns.length) status = 'both'
      else if (errs.length) status = 'err'
      else if (wrns.length) status = 'wrn'
      else status = 'ok'
    }
    slots.push({ slotStart: sS, slotEnd: sE, errors: errs, warnings: wrns, status, active })
  }
  const expectedTotal = Math.max(1, Math.round(periodMs / intervalMs))
  return { slots, intervalMs, expectedTotal, actualTotal: task.runs, completedTotal: task.completedRuns }
}

function getTaskInfo(taskId: string, tasks: TaskCfg[]) {
  const cfg = tasks.find(t => t.id === taskId)
  if (!cfg) {
    const name = taskId.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
    return { name, script: null as string | null, detail: null as string | null, intervalSeconds: 3600 }
  }
  const desc = cfg.description || ''
  const ci = desc.indexOf(':')
  return {
    name: ci > 0 ? desc.slice(0, ci).trim() : taskId,
    script: cfg.script || null,
    detail: ci > 0 ? desc.slice(ci + 1).trim() : desc,
    intervalSeconds: cfg.intervalSeconds,
  }
}

// ── Sub-components ─────────────────────────────────────────────────────────

function BarChart({
  meta,
  onBarClick,
}: {
  meta: SlotMeta
  onBarClick: (slot: Slot, meta: SlotMeta) => void
}) {
  const okN = meta.slots.filter(s => s.status === 'ok').length
  const activeN = meta.slots.filter(s => s.active).length
  const upPct = activeN ? Math.round((okN / activeN) * 100) : 100
  const upColor = upPct === 100 ? '#10b981' : upPct >= 90 ? '#f59e0b' : '#ef4444'
  const startLbl = meta.slots[0] ? fmtDateShort(meta.slots[0].slotStart) : '—'

  return (
    <div className="flex-1 min-w-0 px-2">
      <div className="flex gap-px h-7">
        {meta.slots.map((slot, i) => (
          <div
            key={i}
            className="flex-1 rounded-sm cursor-pointer hover:opacity-70 transition-opacity min-w-px"
            style={{ background: STATUS_COLOR[slot.status] }}
            onClick={e => { e.stopPropagation(); onBarClick(slot, meta) }}
            title={`${fmtDateShort(slot.slotStart)} · E:${slot.errors.length} W:${slot.warnings.length}`}
          />
        ))}
      </div>
      <div className="flex justify-between text-[10px] mt-0.5">
        <span className="text-zinc-600">{startLbl}</span>
        <span style={{ color: upColor }} className="font-medium">{upPct}% clean</span>
        <span className="text-zinc-600">now</span>
      </div>
    </div>
  )
}

function TaskCard({
  taskId,
  tasks,
  reports,
  startMs,
  endMs,
  onBarClick,
}: {
  taskId: string
  tasks: TaskCfg[]
  reports: Record<string, DailyReport>
  startMs: number
  endMs: number
  onBarClick: (slot: Slot, meta: SlotMeta, taskName: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'errors' | 'warnings'>('errors')

  const info = getTaskInfo(taskId, tasks)
  const aggTask = aggregateTask(reports, taskId, startMs, endMs)
  const meta = buildSlots(aggTask, startMs, endMs, info.intervalSeconds)
  const ec = aggTask.errors.length
  const wc = aggTask.warnings.length

  return (
    <div className="card overflow-hidden">
      <div
        className="flex items-center gap-2 px-4 py-2.5 cursor-pointer hover:bg-surface-2/40 transition-colors select-none"
        onClick={() => setOpen(o => !o)}
      >
        <span
          className="text-zinc-500 text-sm shrink-0 transition-transform duration-150"
          style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}
        >›</span>
        <div className="w-40 shrink-0 min-w-0">
          <div className="text-sm font-medium text-zinc-100 truncate">{info.name}</div>
          {info.script && <div className="text-[10px] text-zinc-600 truncate">{info.script}</div>}
        </div>
        <BarChart meta={meta} onBarClick={(s, m) => onBarClick(s, m, info.name)} />
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-zinc-500 tabular-nums w-12 text-right">{aggTask.completedRuns}/{aggTask.runs}</span>
          {ec > 0
            ? <span className="badge border-danger/30 bg-danger/10 text-danger text-[10px]">✕ {ec}</span>
            : <span className="badge border-success/30 bg-success/10 text-success text-[10px]">✓ 0</span>}
          {wc > 0
            ? <span className="badge border-warning/30 bg-warning/10 text-warning text-[10px]">⚠ {wc}</span>
            : <span className="text-[10px] text-zinc-600 w-8 text-center">0</span>}
        </div>
      </div>

      {open && (
        <div className="border-t border-surface-3 px-4 py-3">
          {info.detail && <p className="text-xs text-zinc-400 mb-3 leading-relaxed">{info.detail}</p>}
          {!ec && !wc ? (
            <p className="text-xs text-zinc-500">No errors or warnings recorded.</p>
          ) : (
            <>
              <div className="flex gap-1.5 mb-3">
                {ec > 0 && (
                  <button
                    className={`text-xs px-2 py-1 rounded border transition-colors ${
                      activeTab === 'errors'
                        ? 'border-danger/50 bg-danger/10 text-danger'
                        : 'border-surface-4 text-zinc-500 hover:text-zinc-300'
                    }`}
                    onClick={() => setActiveTab('errors')}
                  >Errors ({ec})</button>
                )}
                {wc > 0 && (
                  <button
                    className={`text-xs px-2 py-1 rounded border transition-colors ${
                      activeTab === 'warnings'
                        ? 'border-warning/50 bg-warning/10 text-warning'
                        : 'border-surface-4 text-zinc-500 hover:text-zinc-300'
                    }`}
                    onClick={() => { setActiveTab('warnings') }}
                  >Warnings ({wc})</button>
                )}
              </div>
              <div className="space-y-1 max-h-44 overflow-y-auto">
                {(activeTab === 'errors' ? aggTask.errors : aggTask.warnings).map((e, i) => (
                  <div key={i} className="flex gap-2 text-xs">
                    <span className="text-zinc-500 shrink-0 tabular-nums font-mono">{fmtTime(e.timestamp)}</span>
                    <span className={activeTab === 'errors' ? 'text-danger/80' : 'text-warning/80'}>{e.message}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function SlotModal({ state, onClose }: { state: ModalState; onClose: () => void }) {
  const { taskName, dateLbl, range, slot, meta } = state
  const dotColor = STATUS_COLOR[slot.status]
  const slotDurMs = slot.slotEnd - slot.slotStart
  const slotExpected = Math.max(1, Math.round(slotDurMs / meta.intervalMs))
  const runColor = meta.actualTotal >= meta.expectedTotal ? '#10b981'
    : meta.actualTotal >= meta.expectedTotal * 0.8 ? '#f59e0b'
    : '#ef4444'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="card w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        <div className="flex items-start justify-between px-5 py-4 border-b border-surface-3 shrink-0">
          <div>
            <div className="font-semibold text-zinc-100">{taskName}</div>
            <div className="text-xs text-zinc-500 mt-0.5">{dateLbl} · {range}</div>
          </div>
          <button className="text-zinc-500 hover:text-zinc-200 text-lg leading-none ml-4" onClick={onClose}>✕</button>
        </div>
        <div className="px-5 py-4 overflow-y-auto space-y-4">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: dotColor }} />
            <span className="text-sm text-zinc-200">{STATUS_LABEL[slot.status]}</span>
          </div>
          <div className="grid grid-cols-3 gap-2 bg-surface-2 rounded-lg p-3">
            <div className="text-center">
              <div className="text-[10px] text-zinc-500 mb-1">Expected</div>
              <div className="text-zinc-100 text-base font-semibold tabular-nums">{meta.expectedTotal}</div>
            </div>
            <div className="text-center border-x border-surface-3">
              <div className="text-[10px] text-zinc-500 mb-1">Executed</div>
              <div className="text-base font-semibold tabular-nums" style={{ color: runColor }}>{meta.actualTotal}</div>
            </div>
            <div className="text-center">
              <div className="text-[10px] text-zinc-500 mb-1">Completed</div>
              <div
                className="text-base font-semibold tabular-nums"
                style={{ color: meta.completedTotal === meta.actualTotal ? '#10b981' : '#f59e0b' }}
              >{meta.completedTotal}</div>
            </div>
          </div>
          <div className="text-[10px] text-zinc-600">counts for full selected period · slot expected: {slotExpected}</div>

          {!slot.active ? (
            <p className="text-xs text-zinc-500">No automation run in this time slot.</p>
          ) : !slot.errors.length && !slot.warnings.length ? (
            <p className="text-xs text-success">✓ No errors or warnings in this slot.</p>
          ) : (
            <div className="space-y-3">
              {slot.errors.length > 0 && (
                <>
                  <div className="section-title">Errors ({slot.errors.length})</div>
                  <div className="space-y-1">
                    {slot.errors.map((e, i) => (
                      <div key={i} className="flex gap-2 text-xs">
                        <span className="text-zinc-500 shrink-0 tabular-nums font-mono">{fmtTime(e.timestamp)}</span>
                        <span className="text-danger/80">{e.message}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {slot.warnings.length > 0 && (
                <>
                  <div className="section-title mt-2">Warnings ({slot.warnings.length})</div>
                  <div className="space-y-1">
                    {slot.warnings.map((w, i) => (
                      <div key={i} className="flex gap-2 text-xs">
                        <span className="text-zinc-500 shrink-0 tabular-nums font-mono">{fmtTime(w.timestamp)}</span>
                        <span className="text-warning/80">{w.message}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function KpiCard({ label, value, sub, accentColor }: {
  label: string
  value: number | string
  sub: string
  accentColor: string
}) {
  return (
    <div className="card p-4" style={{ borderLeft: `3px solid ${accentColor}` }}>
      <div className="text-xs text-zinc-500 mb-1">{label}</div>
      <div className="text-2xl font-semibold tabular-nums text-zinc-100">{value}</div>
      <div className="text-xs text-zinc-600 mt-0.5">{sub}</div>
    </div>
  )
}

function MiniKpi({ label, value, color }: { label: string; value: number | string; color: string }) {
  return (
    <div>
      <div className="text-[10px] text-zinc-500 uppercase tracking-wide">{label}</div>
      <div className="text-lg font-semibold tabular-nums mt-0.5" style={{ color }}>{value}</div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function HealthPage() {
  const [data, setData] = useState<AllReportsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [periodIdx, setPeriodIdx] = useState(4) // 7d default
  const [modal, setModal] = useState<ModalState | null>(null)

  useEffect(() => {
    fetch('/api/reports/all')
      .then(r => r.json())
      .then((d: AllReportsResponse) => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setModal(null) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  const handleBarClick = (slot: Slot, meta: SlotMeta, taskName: string) => {
    const durMs = slot.slotEnd - slot.slotStart
    const longSlot = durMs >= 86_400_000
    const fmt = (d: Date) => longSlot
      ? d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
      : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
    const dateLbl = new Date(slot.slotStart).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
    setModal({ taskName, dateLbl, range: `${fmt(new Date(slot.slotStart))} – ${fmt(new Date(slot.slotEnd))}`, slot, meta })
  }

  if (loading) {
    return (
      <div className="animate-slide_in">
        <PageHeader title="Health Status" icon="💊" subtitle="Automation task health · multi-period" />
        <div className="p-6 space-y-3">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="card h-14 animate-pulse" style={{ background: '#18181b' }} />
          ))}
        </div>
      </div>
    )
  }

  if (!data || !Object.keys(data.reports).length) {
    return (
      <div className="animate-slide_in">
        <PageHeader title="Health Status" icon="💊" subtitle="Automation task health · multi-period" />
        <div className="p-6">
          <div className="card p-5 border-danger/30" style={{ background: 'rgba(239,68,68,0.05)' }}>
            <p className="text-sm text-danger font-medium">No report data found.</p>
            <p className="text-xs text-zinc-500 mt-1">
              Run <code className="font-mono bg-surface-3 px-1 rounded text-zinc-300">08-daily-report.ps1</code> to generate reports.
            </p>
          </div>
        </div>
      </div>
    )
  }

  const { reports, tasks } = data
  const dates = Object.keys(reports).sort().reverse()
  const { startMs, endMs } = getViewRange(reports, periodIdx)
  const taskIds = allTaskIds(reports)

  let allRuns = 0, allErrors = 0, allWarnings = 0
  taskIds.forEach(id => {
    const t = aggregateTask(reports, id, startMs, endMs)
    allRuns += t.runs
    allErrors += t.errors.length
    allWarnings += t.warnings.length
  })

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader
        title="Health Status"
        icon="💊"
        subtitle={`${dates.length} report${dates.length !== 1 ? 's' : ''} · automation task health`}
      />

      <div className="p-6 space-y-5">

        {/* Period selector */}
        <div className="flex flex-wrap gap-1">
          {PERIODS.map((p, i) => (
            <button
              key={p.label}
              onClick={() => setPeriodIdx(i)}
              className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                i === periodIdx
                  ? 'border-primary bg-primary/20 text-white font-medium'
                  : 'border-surface-4 bg-surface-2 text-zinc-400 hover:text-zinc-200 hover:border-surface-3'
              }`}
            >{p.label}</button>
          ))}
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard label="Total Runs" value={allRuns} sub={`${taskIds.length} tasks`} accentColor="#0C5CAB" />
          <KpiCard
            label="Errors"
            value={allErrors}
            sub={allErrors === 0 ? 'All clean' : 'Review'}
            accentColor={allErrors === 0 ? '#10b981' : '#ef4444'}
          />
          <KpiCard
            label="Warnings"
            value={allWarnings}
            sub={allWarnings === 0 ? 'Clean' : 'Review'}
            accentColor={allWarnings === 0 ? '#10b981' : '#f59e0b'}
          />
          <KpiCard
            label="Period"
            value={PERIODS[periodIdx].label}
            sub={`${fmtDateShort(startMs)} → now`}
            accentColor="#10b981"
          />
        </div>

        {/* Task cards */}
        <div>
          <div className="section-title mb-2">Tasks</div>
          <div className="space-y-1.5">
            {taskIds.map(id => (
              <TaskCard
                key={id}
                taskId={id}
                tasks={tasks}
                reports={reports}
                startMs={startMs}
                endMs={endMs}
                onBarClick={handleBarClick}
              />
            ))}
          </div>
        </div>

        {/* Daily history */}
        {dates.length > 0 && (
          <div>
            <div className="section-title mb-2">Daily History</div>
            <div className="space-y-2">
              {dates.map(dateStr => {
                const r = reports[dateStr]
                const s = r.summary
                let totRuns = 0, totDone = 0
                Object.values(r.tasks).forEach(t => { totRuns += t.runs; totDone += t.completedRuns })
                const pct = totRuns ? Math.round((totDone / totRuns) * 100) : 100
                return (
                  <div key={dateStr} className="card p-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <span className="font-medium text-zinc-200 text-sm">{dateStr}</span>
                      <span className="text-[10px] text-zinc-500">{fmtDT(r.periodStart)} → {fmtDT(r.periodEnd)}</span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <MiniKpi label="Total Runs" value={s.totalRuns} color="#0C5CAB" />
                      <MiniKpi label="Errors" value={s.totalErrors} color={s.totalErrors === 0 ? '#10b981' : '#ef4444'} />
                      <MiniKpi label="Warnings" value={s.totalWarnings} color={s.totalWarnings === 0 ? '#10b981' : '#f59e0b'} />
                      <MiniKpi label="Completion" value={`${pct}%`} color="#10b981" />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

      </div>

      {modal && <SlotModal state={modal} onClose={() => setModal(null)} />}
    </div>
  )
}
