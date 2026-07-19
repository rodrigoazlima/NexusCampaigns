'use client'

import { useState } from 'react'
import { Save, Loader2, CheckCircle, AlertTriangle } from 'lucide-react'
import type { AgentSandboxSettings } from '@/lib/types'

interface Props {
  agent: string
  initial: AgentSandboxSettings
}

export default function SandboxConfigForm({ agent, initial }: Props) {
  const [enabled, setEnabled] = useState(initial.enabled)
  const [allowDeletes, setAllowDeletes] = useState(initial.allowDeletes)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  function toggle(value: boolean, setter: (v: boolean) => void) {
    setter(!value)
    setDirty(true)
    if (status !== 'idle') setStatus('idle')
  }

  async function save() {
    setSaving(true)
    setStatus('idle')
    setError(null)
    try {
      const res = await fetch(`/api/agents/${agent}/sandbox`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, allowDeletes }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}) as { error?: string })
        throw new Error(body.error ?? `HTTP ${res.status}`)
      }
      setDirty(false)
      setStatus('success')
      setTimeout(() => setStatus('idle'), 3000)
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="panel p-4">
      <div className="space-y-4 max-w-xl">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={() => toggle(enabled, setEnabled)}
            className="mt-0.5 h-4 w-4 accent-primary"
          />
          <div>
            <div className="text-sm text-zinc-200 font-medium">Route through sandbox</div>
            <div className="text-xs text-zinc-500 mt-0.5">
              The runtime dispatches this agent inside an isolated Podman/Docker container instead of
              running it directly against the live vault. Only the knowledge-base and state files it
              declares get applied to the real vault - everything else the run touches is dropped and
              logged (see Change Log).
            </div>
          </div>
        </label>

        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={allowDeletes}
            onChange={() => toggle(allowDeletes, setAllowDeletes)}
            className="mt-0.5 h-4 w-4 accent-primary"
          />
          <div>
            <div className="text-sm text-zinc-200 font-medium">Allow deletes</div>
            <div className="text-xs text-zinc-500 mt-0.5">
              Propagate in-scope file deletions from inside the sandbox (e.g. the pre-rename half of a
              rename). When off, a rename&apos;s new file still applies but the stale original is left in
              place, logged as dropped.
            </div>
          </div>
        </label>
      </div>

      <div className="flex items-center gap-3 mt-5 pt-4 border-t border-surface-3">
        <button
          onClick={save}
          disabled={saving || !dirty}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary hover:bg-primary/80 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          {saving ? 'Saving…' : 'Save'}
        </button>
        {status === 'success' && (
          <span className="flex items-center gap-1 text-xs text-success">
            <CheckCircle size={12} /> Saved
          </span>
        )}
        {status === 'error' && (
          <span className="flex items-center gap-1 text-xs text-danger">
            <AlertTriangle size={12} /> {error}
          </span>
        )}
        {dirty && status === 'idle' && <span className="text-[10px] text-zinc-600">Unsaved changes</span>}
      </div>
    </div>
  )
}
