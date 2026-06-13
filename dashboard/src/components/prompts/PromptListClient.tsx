'use client'

import { useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Pencil, Trash2, Plus, ChevronDown, ChevronRight, FileText, Check, X } from 'lucide-react'
import type { PromptFile } from '@/lib/types'

interface PromptListClientProps {
  files: PromptFile[]
}

function fileBadge(file: PromptFile): { label: string; cls: string } {
  const parts = file.path.split('/')
  if (file.filename === 'AGENT.md') return { label: 'spec', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' }
  if (parts.includes('prompts')) return { label: 'prompt', cls: 'bg-primary/15 text-primary border-primary/30' }
  return { label: 'doc', cls: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30' }
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  return `${(bytes / 1024).toFixed(1)}KB`
}

// ---------------------------------------------------------------------------
// New File Modal
// ---------------------------------------------------------------------------

function NewFileModal({
  agents,
  onClose,
  onCreated,
}: {
  agents: string[]
  onClose: () => void
  onCreated: () => void
}) {
  const [agent, setAgent] = useState(agents[0] ?? '')
  const [filename, setFilename] = useState('prompts/system.md')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function create() {
    setSaving(true)
    setError(null)
    const relPath = `${agent}/${filename}`
    const res = await fetch('/api/prompts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relPath, content }),
    })
    setSaving(false)
    if (!res.ok) {
      const j = await res.json().catch(() => ({}))
      setError((j as { error?: string }).error ?? `HTTP ${res.status}`)
      return
    }
    onCreated()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-md mx-4 bg-surface-1 border border-surface-3 rounded-xl shadow-2xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-zinc-100">New Prompt File</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-surface-2 text-zinc-400"><X size={15} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-zinc-500 block mb-1">Agent</label>
            <select
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
              className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-primary/60"
            >
              {agents.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-500 block mb-1">Filename (relative to agent folder)</label>
            <input
              type="text"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              placeholder="prompts/system.md"
              className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-primary/60"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 block mb-1">Initial content (optional)</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-primary/60 resize-y"
            />
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200">Cancel</button>
          <button
            onClick={create}
            disabled={saving || !agent || !filename}
            className="px-4 py-1.5 text-xs font-medium bg-primary hover:bg-primary/80 disabled:opacity-50 text-white rounded transition-colors"
          >
            {saving ? 'Creating…' : 'Create File'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Delete confirm row
// ---------------------------------------------------------------------------

function DeleteConfirm({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="flex items-center gap-2 ml-auto">
      <span className="text-xs text-zinc-400">Delete this file?</span>
      <button
        onClick={onConfirm}
        className="px-2 py-1 text-[11px] bg-danger/20 hover:bg-danger/40 text-danger rounded transition-colors"
      >
        Delete
      </button>
      <button
        onClick={onCancel}
        className="px-2 py-1 text-[11px] text-zinc-400 hover:text-zinc-200 transition-colors"
      >
        Cancel
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single file row
// ---------------------------------------------------------------------------

function FileRow({
  file,
  onDeleted,
  onRenamed,
}: {
  file: PromptFile
  onDeleted: (path: string) => void
  onRenamed: (oldPath: string, newPath: string) => void
}) {
  const router = useRouter()
  const [renaming, setRenaming] = useState(false)
  const [renameVal, setRenameVal] = useState(file.filename)
  const [deleting, setDeleting] = useState(false)
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const badge = fileBadge(file)

  function startRename() {
    setRenameVal(file.filename)
    setRenaming(true)
    setTimeout(() => inputRef.current?.select(), 0)
  }

  async function confirmRename() {
    const newName = renameVal.trim()
    if (!newName || newName === file.filename) { setRenaming(false); return }
    const dir = file.path.split('/').slice(0, -1).join('/')
    const to = dir ? `${dir}/${newName}` : newName
    setLoading(true)
    const res = await fetch('/api/prompts/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: file.path, to }),
    })
    setLoading(false)
    setRenaming(false)
    if (res.ok) onRenamed(file.path, to)
  }

  async function confirmDelete() {
    setLoading(true)
    const res = await fetch(`/api/prompts/${file.path}`, { method: 'DELETE' })
    setLoading(false)
    if (res.ok) onDeleted(file.path)
    setDeleting(false)
  }

  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-surface-2 group transition-colors ${loading ? 'opacity-50' : ''}`}>
      <FileText size={14} className="text-zinc-600 shrink-0" />

      <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono shrink-0 ${badge.cls}`}>
        {badge.label}
      </span>

      {renaming ? (
        <input
          ref={inputRef}
          value={renameVal}
          onChange={(e) => setRenameVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') confirmRename(); if (e.key === 'Escape') setRenaming(false) }}
          onBlur={confirmRename}
          className="flex-1 bg-surface-3 border border-primary/60 rounded px-2 py-0.5 text-xs font-mono text-zinc-200 focus:outline-none"
        />
      ) : (
        <span className="flex-1 text-xs font-mono text-zinc-300 truncate" title={file.path}>
          {file.path}
        </span>
      )}

      <span className="text-[10px] text-zinc-600 shrink-0 hidden sm:block">{fmtSize(file.sizeBytes)}</span>
      <span className="text-[10px] text-zinc-600 shrink-0 hidden md:block">{fmtDate(file.modifiedAt)}</span>

      {deleting ? (
        <DeleteConfirm onConfirm={confirmDelete} onCancel={() => setDeleting(false)} />
      ) : (
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-auto shrink-0">
          <button
            onClick={() => router.push(`/prompt/edit/${file.path}`)}
            className="p-1.5 rounded hover:bg-surface-3 text-zinc-500 hover:text-primary transition-colors"
            title="Edit"
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={startRename}
            className="p-1.5 rounded hover:bg-surface-3 text-zinc-500 hover:text-zinc-200 transition-colors"
            title="Rename"
          >
            <Check size={13} />
          </button>
          <button
            onClick={() => setDeleting(true)}
            className="p-1.5 rounded hover:bg-surface-3 text-zinc-500 hover:text-danger transition-colors"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Agent group
// ---------------------------------------------------------------------------

function AgentGroup({
  agent,
  files,
  onDeleted,
  onRenamed,
}: {
  agent: string
  files: PromptFile[]
  onDeleted: (path: string) => void
  onRenamed: (oldPath: string, newPath: string) => void
}) {
  const [open, setOpen] = useState(true)

  return (
    <div className="border border-surface-3 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 bg-surface-2 hover:bg-surface-3 transition-colors text-left"
      >
        {open ? <ChevronDown size={13} className="text-zinc-500" /> : <ChevronRight size={13} className="text-zinc-500" />}
        <span className="text-xs font-mono font-medium text-zinc-300">{agent}</span>
        <span className="text-[10px] text-zinc-600 ml-auto">{files.length} file{files.length !== 1 ? 's' : ''}</span>
      </button>
      {open && (
        <div className="px-1 py-1 space-y-0.5">
          {files.map((f) => (
            <FileRow key={f.path} file={f} onDeleted={onDeleted} onRenamed={onRenamed} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main list component
// ---------------------------------------------------------------------------

export default function PromptListClient({ files: initial }: PromptListClientProps) {
  const [files, setFiles] = useState(initial)
  const [newFileOpen, setNewFileOpen] = useState(false)

  const agents = [...new Set(files.map((f) => f.agent))].sort()

  function handleDeleted(filePath: string) {
    setFiles((prev) => prev.filter((f) => f.path !== filePath))
  }

  function handleRenamed(oldPath: string, newPath: string) {
    setFiles((prev) =>
      prev.map((f) => {
        if (f.path !== oldPath) return f
        const parts = newPath.split('/')
        return { ...f, path: newPath, filename: parts[parts.length - 1], agent: parts[0] }
      })
    )
  }

  function handleCreated() {
    // Refresh page to pick up new file
    window.location.reload()
  }

  const grouped = agents.map((agent) => ({
    agent,
    files: files.filter((f) => f.agent === agent),
  }))

  return (
    <div>
      <div className="flex justify-end mb-4">
        <button
          onClick={() => setNewFileOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary hover:bg-primary/80 text-white rounded transition-colors"
        >
          <Plus size={13} />
          New File
        </button>
      </div>

      <div className="space-y-2">
        {grouped.map(({ agent, files: agentFiles }) => (
          <AgentGroup
            key={agent}
            agent={agent}
            files={agentFiles}
            onDeleted={handleDeleted}
            onRenamed={handleRenamed}
          />
        ))}
      </div>

      {newFileOpen && (
        <NewFileModal
          agents={agents}
          onClose={() => setNewFileOpen(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}
