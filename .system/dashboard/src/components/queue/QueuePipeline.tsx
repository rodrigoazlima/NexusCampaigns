'use client'

import { Fragment, useState } from 'react'
import { createPortal } from 'react-dom'
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

interface PopState { agent: string; top: number; left: number }
interface Props {
  item: QueueItem
  agentStats: Record<string, QueueAgentStat>
}

export default function QueuePipeline({ item, agentStats }: Props) {
  const router = useRouter()
  const [pop, setPop] = useState<PopState | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const toggle = (agent: string, el: HTMLElement) => {
    if (pop?.agent === agent) { setPop(null); return }
    const r = el.getBoundingClientRect()
    setPop({ agent, top: r.bottom + 6, left: r.left + r.width / 2 })
  }

  const reprocess = async (agent: string) => {
    setBusy(agent)
    try {
      const res = await fetch('/api/gm/queue/reprocess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: item.path, agent }),
      })
      if (res.ok) { setPop(null); router.refresh() }
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex items-center">
      {PIPELINE.map((agent, i) => {
        const status = item.agents[agent] ?? 'pending'
        const count = item.reruns[agent] ?? 0
        const prevDone = i > 0 && item.agents[PIPELINE[i - 1]] === 'done'
        return (
          <Fragment key={agent}>
            {i > 0 && (
              <div className={`h-px w-3 ${prevDone ? 'bg-success/40' : 'bg-surface-3'}`} />
            )}
            <button
              type="button"
              onClick={(e) => toggle(agent, e.currentTarget)}
              title={`${agentDisplayName(agent)} — ${status} (click for re-run options)`}
              className="relative flex items-center justify-center"
            >
              <span className={`w-5 h-5 rounded-full border flex items-center justify-center transition-shadow ${NODE_STYLE[status] ?? NODE_STYLE.skip} ${pop?.agent === agent ? 'ring-2 ring-primary/60' : ''} ${status === 'pending' ? 'animate-pulse' : ''}`}>
                <NodeIcon status={status} />
              </span>
              {count > 0 && (
                <span className="absolute -top-1.5 -right-1.5 text-[8px] leading-none px-1 py-0.5 rounded-full bg-primary/20 text-primary font-mono border border-primary/30">
                  {count}
                </span>
              )}
            </button>
          </Fragment>
        )
      })}

      {pop && createPortal(
        <>
          {/* click-away backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setPop(null)} />
          <div
            className="fixed z-50 w-52 p-3 rounded-lg bg-surface-2 border border-surface-3 shadow-2xl -translate-x-1/2"
            style={{ top: pop.top, left: pop.left }}
          >
            {(() => {
              const agent = pop.agent
              const status = item.agents[agent] ?? 'pending'
              const stat = agentStats[agent]
              return (
                <>
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="text-sm font-semibold text-zinc-100">{agentDisplayName(agent)}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase ${NODE_STYLE[status] ?? NODE_STYLE.skip}`}>
                      {status}
                    </span>
                  </div>
                  <div className="space-y-1 text-[11px] text-zinc-500 font-mono mb-3">
                    <div className="flex justify-between"><span>last run</span><span className="text-zinc-300">{stat?.lastRun ? formatRelative(stat.lastRun) : 'never'}</span></div>
                    <div className="flex justify-between"><span>times ran</span><span className="text-zinc-300">{stat?.totalRuns ?? 0}</span></div>
                    <div className="flex justify-between"><span>manual re-runs</span><span className="text-zinc-300">{item.reruns[agent] ?? 0}</span></div>
                  </div>
                  {agent === 'ingestion' ? (
                    <div className="text-[10px] text-zinc-600 italic">Ingestion can’t be re-run.</div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => reprocess(agent)}
                      disabled={busy === agent}
                      className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] font-medium rounded bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 transition-colors disabled:opacity-50"
                    >
                      {busy === agent ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                      Reprocess {agentDisplayName(agent)}
                    </button>
                  )}
                </>
              )
            })()}
          </div>
        </>,
        document.body,
      )}
    </div>
  )
}
