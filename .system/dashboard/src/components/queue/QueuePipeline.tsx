'use client'

import { Fragment, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Check, Minus, AlertTriangle, Dot, RotateCcw, Loader2 } from 'lucide-react'
import type { QueueItem, QueueAgentStat } from '@/lib/types'
import { formatRelative, agentDisplayName } from '@/lib/utils'

// Pipeline order from registry execution_order (per-file agents only).
const PIPELINE: string[] = [
  'ingestion', 'vision', 'lore', 'token', 'wiki', 'classification', 'review', 'wikilink',
]

const NODE_STYLE: Record<string, string> = {
  done:    'bg-success/20 text-success border-success/40',
  pending: 'bg-warning/20 text-warning border-warning/40',
  skip:    'bg-surface-3 text-zinc-600 border-surface-3',
  error:   'bg-danger/20 text-danger border-danger/40',
}

function NodeIcon({ status }: { status: string }) {
  if (status === 'done') return <Check size={11} />
  if (status === 'skip') return <Minus size={11} />
  if (status === 'error') return <AlertTriangle size={11} />
  return <Dot size={14} />   // pending
}

interface Props {
  item: QueueItem
  agentStats: Record<string, QueueAgentStat>
}

export default function QueuePipeline({ item, agentStats }: Props) {
  const router = useRouter()
  const [busy, setBusy] = useState(false)

  const reprocess = async () => {
    setBusy(true)
    try {
      const res = await fetch('/api/gm/queue/reprocess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: item.path }),
      })
      if (res.ok) router.refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-3">
      {/* Pipeline timeline */}
      <div className="flex items-center">
        {PIPELINE.map((agent, i) => {
          const status = item.agents[agent] ?? 'pending'
          const stat = agentStats[agent]
          const lastRun = stat?.lastRun ? formatRelative(stat.lastRun) : 'never'
          const ran = stat?.totalRuns ?? 0
          const prevDone = i > 0 && item.agents[PIPELINE[i - 1]] === 'done'
          return (
            <Fragment key={agent}>
              {i > 0 && (
                <div className={`h-px w-3 ${prevDone ? 'bg-success/40' : 'bg-surface-3'}`} />
              )}
              <div
                className="group relative flex items-center justify-center"
                title={`${agentDisplayName(agent)} — ${status}\nlast run: ${lastRun}\ntimes ran: ${ran}\nmanual re-runs: ${item.reruns}`}
              >
                <div className={`w-5 h-5 rounded-full border flex items-center justify-center ${NODE_STYLE[status] ?? NODE_STYLE.skip} ${status === 'pending' ? 'animate-pulse' : ''}`}>
                  <NodeIcon status={status} />
                </div>

                {/* Styled hover card */}
                <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block z-50 w-44 p-2.5 rounded-lg bg-surface-2 border border-surface-3 shadow-xl text-left">
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <span className="text-xs font-semibold text-zinc-200">{agentDisplayName(agent)}</span>
                    <span className={`text-[9px] px-1 py-0.5 rounded font-semibold uppercase ${NODE_STYLE[status] ?? NODE_STYLE.skip}`}>{status}</span>
                  </div>
                  <div className="space-y-0.5 text-[10px] text-zinc-500 font-mono">
                    <div className="flex justify-between"><span>last run</span><span className="text-zinc-300">{lastRun}</span></div>
                    <div className="flex justify-between"><span>times ran</span><span className="text-zinc-300">{ran}</span></div>
                    <div className="flex justify-between"><span>manual re-runs</span><span className="text-zinc-300">{item.reruns}</span></div>
                  </div>
                </div>
              </div>
            </Fragment>
          )
        })}
      </div>

      {/* Manual re-run count */}
      {item.reruns > 0 && (
        <span className="flex items-center gap-0.5 text-[10px] text-zinc-500 font-mono" title={`${item.reruns} manual re-run(s)`}>
          <RotateCcw size={10} /> {item.reruns}
        </span>
      )}

      {/* Reprocess / re-run button */}
      <button
        onClick={reprocess}
        disabled={busy}
        title="Flag for re-run / reprocess — resets completed stages to pending and flags this source's drafts as needs_reprocessing"
        className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 transition-colors disabled:opacity-50 whitespace-nowrap"
      >
        {busy ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
        Reprocess
      </button>
    </div>
  )
}
