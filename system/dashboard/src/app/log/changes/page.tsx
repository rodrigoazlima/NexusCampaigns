export const dynamic = 'force-dynamic'

import { readSandboxRuns } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import { History } from 'lucide-react'
import type { SandboxFileChange, SandboxRun } from '@/lib/types'

function DiffView({ diff }: { diff: string }) {
  if (!diff) return null
  const lines = diff.split('\n')
  return (
    <pre className="text-xs font-mono overflow-x-auto bg-surface-1 rounded p-3 leading-5">
      {lines.map((line, i) => {
        let cls = 'text-zinc-500'
        if (line.startsWith('+') && !line.startsWith('+++')) cls = 'text-success'
        else if (line.startsWith('-') && !line.startsWith('---')) cls = 'text-danger'
        else if (line.startsWith('@@')) cls = 'text-primary'
        return (
          <div key={i} className={cls}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}

function FileChangeRow({ change }: { change: SandboxFileChange }) {
  const applied = change.status === 'applied' || change.status === 'would-apply'
  return (
    <details>
      <summary
        className={`cursor-pointer list-none px-4 py-2 flex items-center justify-between gap-3 hover:bg-surface-2 border-l-2 ${applied ? 'border-success' : 'border-warning'}`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-surface-3 text-zinc-400 shrink-0">
            {change.class}
          </span>
          <span className="font-mono text-xs text-zinc-300 truncate">{change.path}</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {change.reason && <span className="text-xs text-warning">{change.reason}</span>}
          <span className="text-xs font-mono text-zinc-500">
            {change.bytesBefore}&rarr;{change.bytesAfter}B
          </span>
        </div>
      </summary>
      <div className="px-4 pb-3 pt-1">
        {change.binary ? (
          <div className="text-xs text-zinc-500 font-mono">
            binary &mdash; {change.bytesBefore}&rarr;{change.bytesAfter} bytes
          </div>
        ) : (
          <DiffView diff={change.diff} />
        )}
      </div>
    </details>
  )
}

function RunPanel({ run }: { run: SandboxRun }) {
  const applied = run.changes.filter((c) => c.status === 'applied' || c.status === 'would-apply')
  const dropped = run.changes.filter((c) => c.status === 'dropped' || c.status === 'would-drop')
  const exitOk = run.containerExitCode === 0

  return (
    <details className="panel overflow-hidden mb-3">
      <summary className="cursor-pointer list-none px-4 py-3 flex items-center justify-between gap-3 flex-wrap hover:bg-surface-2">
        <div className="flex items-center gap-3 flex-wrap min-w-0">
          <span className="text-xs font-mono text-zinc-500">{run.startedAt}</span>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-primary/10 text-primary">[{run.agent}]</span>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-surface-3 text-zinc-400">{run.runtime}</span>
          {run.dryRun && (
            <span className="text-xs font-mono px-2 py-0.5 rounded bg-warning/10 text-warning">dry-run</span>
          )}
          <span
            className={`text-xs font-mono px-2 py-0.5 rounded ${exitOk ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'}`}
          >
            exit {run.containerExitCode}
          </span>
        </div>
        <div className="flex items-center gap-3 shrink-0 text-xs font-mono">
          <span className="text-success">{applied.length} applied</span>
          <span className="text-warning">{dropped.length} dropped</span>
        </div>
      </summary>

      <div className="border-t border-surface-3">
        {applied.length > 0 && (
          <div>
            <div className="px-4 py-2 text-xs font-semibold text-success bg-success/5">Applied</div>
            <div className="divide-y divide-surface-3">
              {applied.map((c) => (
                <FileChangeRow key={c.path} change={c} />
              ))}
            </div>
          </div>
        )}
        {dropped.length > 0 && (
          <div>
            <div className="px-4 py-2 text-xs font-semibold text-warning bg-warning/5">Dropped</div>
            <div className="divide-y divide-surface-3">
              {dropped.map((c) => (
                <FileChangeRow key={c.path} change={c} />
              ))}
            </div>
          </div>
        )}
        {run.changes.length === 0 && (
          <div className="px-4 py-3 text-xs text-zinc-500">No file changes detected.</div>
        )}
      </div>
    </details>
  )
}

export default async function ChangesLogPage() {
  const runs = await Promise.resolve(readSandboxRuns())
  const totalApplied = runs.reduce((s, r) => s + r.summary.applied, 0)
  const totalDropped = runs.reduce((s, r) => s + r.summary.dropped, 0)
  const lastRun = runs[0] ?? null

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={History}
        title="Change Log"
        subtitle="Sandboxed agent runs — applied vs dropped file changes"
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Total Runs</div>
          <div className="text-3xl font-mono font-semibold text-zinc-200">{runs.length}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Applied</div>
          <div className="text-3xl font-mono font-semibold text-success">{totalApplied}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Dropped</div>
          <div className="text-3xl font-mono font-semibold text-warning">{totalDropped}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Last Run</div>
          <div
            className={`text-3xl font-mono font-semibold ${
              lastRun ? (lastRun.containerExitCode === 0 ? 'text-success' : 'text-danger') : 'text-zinc-500'
            }`}
          >
            {lastRun ? `exit ${lastRun.containerExitCode}` : '—'}
          </div>
        </div>
      </div>

      {runs.length === 0 ? (
        <div className="panel p-8 text-center text-zinc-500 text-sm">
          No sandbox runs yet &mdash; run{' '}
          <code className="font-mono text-xs bg-surface-2 px-1.5 py-0.5 rounded">
            python -m nexus.tasks.sandbox_run --agent &lt;name&gt;
          </code>
        </div>
      ) : (
        <div>
          {runs.map((run) => (
            <RunPanel key={run.runId} run={run} />
          ))}
        </div>
      )}
    </div>
  )
}
