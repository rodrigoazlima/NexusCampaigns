'use client'

import { useState, useTransition } from 'react'

const MODELS = [
  { value: '', label: '— none —' },
  { value: 'claude-opus-4-8',              label: 'Claude Opus 4.8' },
  { value: 'claude-sonnet-4-6',            label: 'Claude Sonnet 4.6' },
  { value: 'claude-haiku-4-5-20251001',    label: 'Claude Haiku 4.5' },
  { value: 'qwen/qwen2.5-vl-72b-instruct', label: 'Qwen2.5-VL 72B' },
  { value: 'qwen/qwen2.5-vl-7b-instruct',  label: 'Qwen2.5-VL 7B' },
]

interface Props {
  agentId: string
  currentModel?: string
}

export function AgentModelSelect({ agentId, currentModel }: Props) {
  const [model, setModel] = useState(currentModel ?? '')
  const [saved, setSaved] = useState(false)
  const [pending, startTransition] = useTransition()

  function handleChange(value: string) {
    setModel(value)
    setSaved(false)
    startTransition(async () => {
      await fetch(`/api/agents/${agentId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: value }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    })
  }

  return (
    <div className="flex items-center gap-1.5">
      <select
        value={model}
        onChange={e => handleChange(e.target.value)}
        disabled={pending}
        className="bg-surface-2 border border-surface-3 text-xs text-neutral rounded px-2 py-1 focus:outline-none focus:border-primary disabled:opacity-50 cursor-pointer hover:border-neutral transition-colors"
      >
        {MODELS.map(m => (
          <option key={m.value} value={m.value}>{m.label}</option>
        ))}
      </select>
      {saved && <span className="text-xs text-success">✓</span>}
    </div>
  )
}
