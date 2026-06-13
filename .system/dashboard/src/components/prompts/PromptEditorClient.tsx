'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import { ArrowLeft, Save, Loader2, CheckCircle, AlertTriangle } from 'lucide-react'

import '@uiw/react-md-editor/markdown-editor.css'
import '@uiw/react-markdown-preview/markdown.css'

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false })

interface Props {
  relPath: string
  initialContent: string
}

export default function PromptEditorClient({ relPath, initialContent }: Props) {
  const router = useRouter()
  const [content, setContent] = useState(initialContent)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)

  const parts = relPath.split('/')
  const agent = parts[0]
  const filename = parts[parts.length - 1]

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const save = useCallback(async () => {
    setSaving(true)
    setSaveStatus('idle')
    setSaveError(null)
    try {
      const res = await fetch(`/api/prompts/${relPath}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setDirty(false)
      setSaveStatus('success')
      setTimeout(() => setSaveStatus('idle'), 3000)
    } catch (err) {
      setSaveStatus('error')
      setSaveError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }, [relPath, content])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        if (!saving) save()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [save, saving])

  function handleChange(val: string | undefined) {
    setContent(val ?? '')
    if (!dirty) setDirty(true)
    if (saveStatus !== 'idle') setSaveStatus('idle')
  }

  function handleBack() {
    if (dirty && !window.confirm('You have unsaved changes. Leave anyway?')) return
    router.push('/prompt')
  }

  return (
    <div className="flex flex-col h-full" data-color-mode="dark">
      {/* Header */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-3 border-b border-surface-3 bg-surface-1">
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
        >
          <ArrowLeft size={14} />
          Back
        </button>

        <div className="h-4 w-px bg-surface-3" />

        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-zinc-500 font-mono">{agent}</span>
          <span className="text-zinc-600">/</span>
          <span className="text-zinc-200 font-mono font-medium">{filename}</span>
          {dirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 ml-1" title="Unsaved changes" />}
        </div>

        <div className="ml-auto flex items-center gap-3">
          {saveStatus === 'success' && (
            <span className="flex items-center gap-1 text-xs text-success">
              <CheckCircle size={12} /> Saved
            </span>
          )}
          {saveStatus === 'error' && (
            <span className="flex items-center gap-1 text-xs text-danger">
              <AlertTriangle size={12} /> {saveError}
            </span>
          )}
          <span className="text-[10px] text-zinc-600">Ctrl+S to save</span>
          <button
            onClick={save}
            disabled={saving || !dirty}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary hover:bg-primary/80 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded transition-colors"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 overflow-hidden">
        <MDEditor
          value={content}
          onChange={handleChange}
          height="100%"
          style={{ height: '100%', borderRadius: 0 }}
          visibleDragbar={false}
        />
      </div>
    </div>
  )
}
