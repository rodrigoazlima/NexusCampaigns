'use client'

import { useState, useTransition } from 'react'
import { Pencil, X } from 'lucide-react'

const MODELS = [
  { value: '',                               label: '— none —' },
  { value: 'claude-opus-4-8',               label: 'Claude Opus 4.8' },
  { value: 'claude-sonnet-4-6',             label: 'Claude Sonnet 4.6' },
  { value: 'claude-haiku-4-5-20251001',     label: 'Claude Haiku 4.5' },
  { value: 'qwen/qwen2.5-vl-72b-instruct',  label: 'Qwen2.5-VL 72B' },
  { value: 'qwen/qwen2.5-vl-7b-instruct',   label: 'Qwen2.5-VL 7B' },
]

const INTERVAL_PRESETS = [
  { label: '15m', value: 900 },
  { label: '30m', value: 1800 },
  { label: '1h',  value: 3600 },
  { label: '6h',  value: 21600 },
  { label: '24h', value: 86400 },
]

interface Props {
  agentId: string
  agentName: string
  currentModel?: string
  currentInterval: number
}

export function AgentEditButton({ agentId, agentName, currentModel, currentInterval }: Props) {
  const [open, setOpen]           = useState(false)
  const [model, setModel]         = useState(currentModel ?? '')
  const [interval, setIntervalV]  = useState(currentInterval)
  const [saved, setSaved]         = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  function handleSave() {
    setError(null)
    startTransition(async () => {
      const res = await fetch(`/api/agents/${agentId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, intervalSeconds: interval }),
      })
      if (!res.ok) {
        const data = await res.json() as { error?: string }
        setError(data.error ?? 'Save failed')
        return
      }
      setSaved(true)
      setTimeout(() => { setSaved(false); setOpen(false) }, 900)
    })
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="p-1 rounded text-neutral hover:text-white hover:bg-surface-3 transition-colors"
        title={`Edit ${agentName}`}
      >
        <Pencil size={13} />
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />
          <div className="relative card p-5 w-80 space-y-4 z-10">

            {/* Header */}
            <div className="flex items-center justify-between">
              <span className="font-medium text-sm text-white">{agentName}</span>
              <button
                onClick={() => setOpen(false)}
                className="p-1 rounded text-neutral hover:text-white hover:bg-surface-3 transition-colors"
              >
                <X size={14} />
              </button>
            </div>

            {/* Model */}
            <div className="space-y-1.5">
              <label className="text-xs text-neutral uppercase tracking-wider">Model</label>
              <select
                value={model}
                onChange={e => setModel(e.target.value)}
                className="w-full bg-surface-2 border border-surface-3 text-xs text-white rounded px-2 py-1.5 focus:outline-none focus:border-primary cursor-pointer"
              >
                {MODELS.map(m => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
            </div>

            {/* Interval */}
            <div className="space-y-1.5">
              <label className="text-xs text-neutral uppercase tracking-wider">Interval</label>
              <div className="flex gap-1.5 flex-wrap">
                {INTERVAL_PRESETS.map(p => (
                  <button
                    key={p.value}
                    onClick={() => setIntervalV(p.value)}
                    className={`text-xs px-2.5 py-1 rounded transition-colors ${
                      interval === p.value
                        ? 'bg-primary text-white'
                        : 'bg-surface-2 text-neutral hover:bg-surface-3 hover:text-white'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <input
                type="number"
                value={interval}
                onChange={e => setIntervalV(Math.max(60, Number(e.target.value)))}
                min={60}
                className="w-full bg-surface-2 border border-surface-3 text-xs text-white rounded px-2 py-1.5 focus:outline-none focus:border-primary"
                placeholder="seconds"
              />
              <div className="text-xs text-neutral/60">
                {interval >= 3600
                  ? `${interval / 3600}h`
                  : `${Math.round(interval / 60)}m`}
              </div>
            </div>

            {error && <p className="text-xs text-danger">{error}</p>}

            <button
              onClick={handleSave}
              disabled={pending}
              className="btn-primary w-full justify-center text-xs py-1.5 disabled:opacity-50"
            >
              {saved ? '✓ Saved' : pending ? 'Saving…' : 'Save changes'}
            </button>

          </div>
        </div>
      )}
    </>
  )
}
