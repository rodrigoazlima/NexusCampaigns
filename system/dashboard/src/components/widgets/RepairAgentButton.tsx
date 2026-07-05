'use client'

import { useState } from 'react'
import { Wrench, Loader2, Check, X } from 'lucide-react'

export default function RepairAgentButton({ agent, error }: { agent: string; error: string }) {
  const [state, setState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')

  const run = async () => {
    setState('running')
    try {
      const res = await fetch('/api/repair/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent, error }),
      })
      setState(res.ok ? 'done' : 'error')
    } catch {
      setState('error')
    } finally {
      setTimeout(() => setState('idle'), 3000)
    }
  }

  return (
    <button
      onClick={run}
      disabled={state === 'running'}
      title={`Run repair agent for [${agent}]`}
      className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-surface-3 text-zinc-300 hover:bg-surface-2 hover:text-white transition-colors disabled:opacity-60"
    >
      {state === 'running' && <Loader2 size={12} className="animate-spin" />}
      {state === 'done' && <Check size={12} className="text-success" />}
      {state === 'error' && <X size={12} className="text-danger" />}
      {state === 'idle' && <Wrench size={12} />}
      Repair
    </button>
  )
}
