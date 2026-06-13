'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { cn, typeIcon, statusBadge } from '@/lib/utils'
import type { ReviewItem, ReviewStatus } from '@/lib/types'

const ALLOWED_TYPES = [
  'npc', 'character', 'faction', 'location', 'city', 'village',
  'dungeon', 'item', 'artifact', 'quest', 'encounter', 'creature',
  'monster', 'event', 'religion', 'organization', 'timeline', 'lore',
]

// Only these four agents can re-process entities
const REPROCESS_AGENTS = ['ingestion-agent', 'vision-agent', 'lore-agent', 'wiki-agent']

const AGENT_LABELS: Record<string, string> = {
  'ingestion-agent': '📥 Ingest',
  'vision-agent':    '👁 Vision',
  'lore-agent':      '📖 Lore',
  'wiki-agent':      '🔗 Wiki',
}

interface Props {
  item: ReviewItem
  body: string
  agents: Array<{ id: string; description: string }>
}

export function ReviewEditor({ item, body, agents }: Props) {
  const router = useRouter()

  const [quality, setQuality]       = useState(item.quality > 0 ? item.quality : (item.suggestedQuality ?? 0))
  const [status, setStatus]         = useState<ReviewStatus>(item.status)
  const [reviewed, setReviewed]     = useState(item.reviewed)
  const [entityType, setEntityType] = useState(item.type)
  const [entityId, setEntityId]     = useState(item.id)
  const [filename, setFilename]     = useState(item.filename)
  const [sourceList, setSourceList] = useState<string[]>(item.source)
  const [newSource, setNewSource]   = useState('')
  const [tags, setTags]             = useState<string[]>(item.tags)
  const [relationships, setRels]    = useState<string[]>(item.relationships)
  const [newTag, setNewTag]         = useState('')
  const [newRel, setNewRel]         = useState('')
  const [saving, setSaving]         = useState(false)
  const [promoting, setPromoting]   = useState(false)
  const [archiving, setArchiving]   = useState(false)
  const [msg, setMsg]               = useState<{ text: string; ok: boolean } | null>(null)
  const [done, setDone]             = useState(false)
  const [runningAgent, setRunningAgent] = useState<string | null>(null)
  const [agentMsg, setAgentMsg]     = useState<{ text: string; ok: boolean } | null>(null)
  const [agentNotes, setAgentNotes] = useState<Record<string, string>>(item.agentNotes ?? {})
  const [pendingAgent, setPendingAgent] = useState<{ id: string; label: string; description: string } | null>(null)
  const [dialogNote, setDialogNote] = useState('')

  // Cache-bust token URL
  const [tokenUrl] = useState(() =>
    item.tokenUrl ? `${item.tokenUrl}&t=${Date.now()}` : null
  )

  const encoded = encodeURIComponent(item.sha256 ?? item.filename)

  async function save() {
    setSaving(true); setMsg(null)
    try {
      const r = await fetch(`/api/review/${encoded}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          quality, status, reviewed, tags, relationships,
          type: entityType,
          id: entityId,
          source: sourceList,
          filename,
          agent_notes: agentNotes,
        }),
      })
      const data = await r.json() as { success?: boolean; newIdentifier?: string; error?: string }
      if (!r.ok) throw new Error(data.error ?? await r.text())
      if (data.newIdentifier && data.newIdentifier !== (item.sha256 ?? item.filename)) {
        router.replace(`/review/${encodeURIComponent(data.newIdentifier)}`)
        return
      }
      setMsg({ text: 'Saved', ok: true })
    } catch (e) {
      setMsg({ text: String(e), ok: false })
    } finally {
      setSaving(false)
    }
  }

  async function promote() {
    if (!confirm(`Promote "${filename}" to 02-Library/?`)) return
    setPromoting(true); setMsg(null)
    try {
      await fetch(`/api/review/${encoded}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          quality, status: 'approved', reviewed: true, tags, relationships,
          type: entityType, id: entityId, source: sourceList, filename,
        }),
      })
      const r = await fetch(`/api/review/${encoded}/promote`, { method: 'POST' })
      if (!r.ok) throw new Error(await r.text())
      setMsg({ text: 'Promoted → 02-Library/', ok: true })
      setStatus('approved'); setReviewed(true); setDone(true)
    } catch (e) {
      setMsg({ text: String(e), ok: false })
    } finally {
      setPromoting(false)
    }
  }

  async function archive() {
    if (!confirm(`Move "${filename}" to 99-Archive/?`)) return
    setArchiving(true); setMsg(null)
    try {
      const r = await fetch(`/api/review/${encoded}/archive`, { method: 'POST' })
      if (!r.ok) throw new Error(await r.text())
      setMsg({ text: 'Archived → 99-Archive/', ok: true })
      setStatus('archived'); setDone(true)
    } catch (e) {
      setMsg({ text: String(e), ok: false })
    } finally {
      setArchiving(false)
    }
  }

  function openAgentDialog(agentId: string, label: string, description: string) {
    setDialogNote(agentNotes[agentId] ?? '')
    setPendingAgent({ id: agentId, label, description })
  }

  async function confirmAgentRun() {
    if (!pendingAgent) return
    const { id: agentId, label } = pendingAgent
    setPendingAgent(null)

    // Persist note to frontmatter first
    const updatedNotes = { ...agentNotes, [agentId]: dialogNote }
    setAgentNotes(updatedNotes)
    await fetch(`/api/review/${encoded}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_notes: updatedNotes }),
    })

    setRunningAgent(label); setAgentMsg(null)
    try {
      const r = await fetch('/api/agents/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agentId }),
      })
      const data = await r.json() as { success?: boolean; error?: string }
      if (!r.ok || !data.success) throw new Error(data.error ?? 'Agent failed')
      setAgentMsg({ text: `${label} completed`, ok: true })
      router.refresh()
    } catch (e) {
      setAgentMsg({ text: String(e), ok: false })
    } finally {
      setRunningAgent(null)
    }
  }

  function addTag() {
    const t = newTag.trim()
    if (t && !tags.includes(t)) { setTags([...tags, t]); setNewTag('') }
  }

  function addRel() {
    const r = newRel.trim()
    if (!r) return
    const v = r.startsWith('[[') ? r : `[[${r}]]`
    if (!relationships.includes(v)) { setRels([...relationships, v]); setNewRel('') }
  }

  function addSource() {
    const s = newSource.trim()
    if (s && !sourceList.includes(s)) { setSourceList([...sourceList, s]); setNewSource('') }
  }

  const qColor = quality >= 7 ? 'text-success' : quality >= 4 ? 'text-warning' : quality > 0 ? 'text-danger' : 'text-neutral'
  const canPromote = quality >= 7 && !done

  return (
    <div className="flex flex-col h-screen overflow-hidden">

      {/* ── Loading overlay ── */}
      {runningAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm">
          <div className="card p-8 flex flex-col items-center gap-5 min-w-[320px] border-primary/30">
            <div className="w-10 h-10 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <div className="text-white font-semibold text-base">Running {runningAgent}…</div>
            <div className="text-neutral text-sm text-center leading-relaxed">
              Processing vault. This may take a few minutes.<br/>
              Edits are locked until complete.
            </div>
          </div>
        </div>
      )}

      {/* ── Agent context dialog ── */}
      {pendingAgent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="card w-[480px] max-w-[95vw] flex flex-col gap-0 border-primary/30 overflow-hidden">
            {/* Header */}
            <div className="px-5 py-3.5 border-b border-surface-3 flex items-center gap-2">
              <span className="text-base">{AGENT_LABELS[pendingAgent.id]?.split(' ')[0] ?? '⚙'}</span>
              <div>
                <div className="text-white font-semibold text-sm">{pendingAgent.label}</div>
                <div className="text-neutral text-xs truncate max-w-sm">{pendingAgent.description}</div>
              </div>
            </div>
            {/* Body */}
            <div className="px-5 py-4 space-y-3">
              <div>
                <label className="text-neutral text-xs uppercase tracking-wide block mb-1.5">
                  Additional context for this run
                </label>
                <textarea
                  value={dialogNote}
                  onChange={e => setDialogNote(e.target.value)}
                  autoFocus
                  rows={5}
                  placeholder={`Describe what to focus on, what this entity is, special instructions…\ne.g. "This is the main villain. Focus on the scar on his left cheek."`}
                  className="w-full bg-surface-2 border border-surface-3 rounded px-3 py-2 text-sm text-white placeholder-neutral focus:outline-none focus:border-primary resize-none font-mono leading-relaxed"
                />
              </div>
              {agentNotes[pendingAgent.id] && agentNotes[pendingAgent.id] !== dialogNote && (
                <div className="text-xs text-neutral">
                  Previous note: <span className="text-zinc-400 italic">&ldquo;{agentNotes[pendingAgent.id].slice(0, 120)}{agentNotes[pendingAgent.id].length > 120 ? '…' : ''}&rdquo;</span>
                </div>
              )}
            </div>
            {/* Footer */}
            <div className="px-5 py-3 border-t border-surface-3 flex items-center justify-end gap-2">
              <button
                onClick={() => setPendingAgent(null)}
                className="btn text-xs px-4 py-1.5 bg-surface-3 border-surface-4 text-zinc-300 hover:bg-surface-4"
              >
                Cancel
              </button>
              <button
                onClick={confirmAgentRun}
                className="btn text-xs px-4 py-1.5 bg-primary/20 border-primary/40 text-primary hover:bg-primary/30"
              >
                Run {pendingAgent.label} →
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Top bar ── */}
      <div className="shrink-0 bg-surface-1 border-b border-surface-3 px-5 py-2.5 flex items-center gap-3 z-10">
        <Link href="/review" className="text-neutral hover:text-white transition-colors text-sm flex items-center gap-1">
          ← Queue
        </Link>
        <span className="text-surface-4">|</span>
        <span className="text-base leading-none">{typeIcon(entityType)}</span>
        <span className="text-white font-medium font-mono text-sm truncate max-w-xs">{filename}</span>
        <span className={cn('badge ml-0.5', statusBadge(status))}>{status}</span>
        {item.isOrphan && <span className="badge bg-danger/20 text-danger border-danger/30">⚠ orphan</span>}

        <div className="flex-1" />

        {agentMsg && (
          <span className={cn('text-sm shrink-0', agentMsg.ok ? 'text-success' : 'text-danger')}>
            {agentMsg.ok ? '✓' : '✗'} {agentMsg.text}
          </span>
        )}

        {msg && (
          <span className={cn('text-sm shrink-0', msg.ok ? 'text-success' : 'text-danger')}>
            {msg.ok ? '✓' : '✗'} {msg.text}
          </span>
        )}

        {!done ? (
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={save}
              disabled={saving || !!runningAgent}
              className="btn text-xs px-3 py-1.5"
            >
              {saving ? '…' : '💾 Save'}
            </button>
            <button
              onClick={promote}
              disabled={!canPromote || promoting || !!runningAgent}
              title={quality < 7 ? 'Quality must be ≥ 7 to promote' : 'Promote to 02-Library/'}
              className={cn('btn text-xs px-3 py-1.5', canPromote
                ? 'bg-success/15 border-success/40 text-success hover:bg-success/25'
                : 'opacity-40 cursor-not-allowed'
              )}
            >
              {promoting ? '…' : '⬆ Promote'}
            </button>
            <button
              onClick={archive}
              disabled={archiving || !!runningAgent}
              className="btn text-xs px-3 py-1.5 bg-danger/10 border-danger/30 text-danger hover:bg-danger/20"
            >
              {archiving ? '…' : '🗄 Archive'}
            </button>
          </div>
        ) : (
          <Link href="/review" className="btn text-xs px-3 py-1.5 bg-primary/20 border-primary/40 text-primary hover:bg-primary/30">
            ← Back to Queue
          </Link>
        )}
      </div>

      {/* ── Main ── */}
      <div className={cn('flex flex-1 overflow-hidden', runningAgent && 'pointer-events-none select-none opacity-60')}>

        {/* ── Left: content + image ── */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 min-w-0">

          {(item.imageUrl || tokenUrl) && (
            <div className="card overflow-hidden">
              <div className="px-4 py-2 border-b border-surface-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="section-title">Images</span>
                  {tokenUrl && <span className="badge bg-surface-3 text-neutral border-surface-4 normal-case font-normal tracking-normal">token generated</span>}
                </div>
                <Link
                  href={`/review/${encoded}/token`}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                >
                  🎨 Edit Token
                </Link>
              </div>
              <div className={`flex gap-0 ${item.imageUrl ? 'divide-x divide-surface-3' : ''}`}>
                {item.imageUrl && (
                  <div className="flex-1 flex flex-col">
                    <div className="px-3 py-1.5 text-xs text-neutral border-b border-surface-3/50">Source</div>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={item.imageUrl} alt={item.id} className="w-full max-h-72 object-contain bg-zinc-950" />
                  </div>
                )}
                {item.imageUrl && (
                  <div className="flex flex-col items-center justify-center bg-zinc-950 px-6 py-4 gap-2 shrink-0 min-w-[140px]">
                    <div className="text-xs text-neutral">Token</div>
                    {tokenUrl ? (
                      <>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={tokenUrl} alt={`${item.id} token`} className="w-32 h-32 object-contain" />
                        <Link
                          href={`/review/${encoded}/token`}
                          className="text-xs text-primary hover:underline"
                        >
                          Edit →
                        </Link>
                      </>
                    ) : (
                      <>
                        <div className="w-32 h-32 border border-dashed border-surface-4 rounded flex items-center justify-center text-neutral text-xs text-center leading-relaxed">
                          No token
                        </div>
                        <Link
                          href={`/review/${encoded}/token`}
                          className="text-xs text-primary hover:underline"
                        >
                          Create →
                        </Link>
                      </>
                    )}
                  </div>
                )}
                {!item.imageUrl && tokenUrl && (
                  <div className="flex flex-col items-center justify-center bg-zinc-950 px-6 py-4 gap-2 shrink-0">
                    <div className="text-xs text-neutral">Token</div>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={tokenUrl} alt={`${item.id} token`} className="w-32 h-32 object-contain" />
                    <Link
                      href={`/review/${encoded}/token`}
                      className="text-xs text-primary hover:underline"
                    >
                      Edit →
                    </Link>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-surface-3 flex items-center justify-between">
              <div className="section-title">Content</div>
              <span className="text-xs text-neutral font-mono">01-Processing/{filename}.md</span>
            </div>
            <pre className="p-4 text-sm text-zinc-300 whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto">
              {body.trim()}
            </pre>
          </div>
        </div>

        {/* ── Right: metadata editor ── */}
        <div className="w-72 shrink-0 border-l border-surface-3 bg-surface-1 overflow-y-auto">
          <div className="p-4 space-y-5">

            {/* Identity */}
            <section>
              <div className="section-title mb-3">Identity</div>
              <div className="space-y-3">

                {item.sha256 && (
                  <div>
                    <label className="text-neutral text-xs uppercase tracking-wide block mb-1">SHA256</label>
                    <span className="font-mono text-[10px] text-zinc-500 break-all">{item.sha256}</span>
                  </div>
                )}

                <div>
                  <label className="text-neutral text-xs uppercase tracking-wide block mb-1">Type</label>
                  <select
                    value={entityType}
                    onChange={e => setEntityType(e.target.value)}
                    className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-primary"
                  >
                    {ALLOWED_TYPES.map(t => (
                      <option key={t} value={t}>{typeIcon(t)} {t}</option>
                    ))}
                    {!ALLOWED_TYPES.includes(entityType) && (
                      <option value={entityType}>{entityType}</option>
                    )}
                  </select>
                </div>

                <div>
                  <label className="text-neutral text-xs uppercase tracking-wide block mb-1">ID</label>
                  <input
                    value={entityId}
                    onChange={e => setEntityId(e.target.value)}
                    className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-primary"
                    placeholder="entity-slug"
                  />
                </div>

                <div>
                  <label className="text-neutral text-xs uppercase tracking-wide block mb-1">Filename</label>
                  <div className="flex gap-1 items-center">
                    <input
                      value={filename}
                      onChange={e => setFilename(e.target.value)}
                      className="flex-1 bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-primary"
                      placeholder="filename-without-extension"
                    />
                    <span className="text-neutral text-xs shrink-0">.md</span>
                  </div>
                  {filename !== item.filename && (
                    <div className="text-xs text-warning mt-1">File will be renamed on save</div>
                  )}
                </div>

                <div>
                  <label className="text-neutral text-xs uppercase tracking-wide block mb-1">Source</label>
                  <div className="space-y-1 mb-1.5">
                    {sourceList.map(s => (
                      <div key={s} className="flex items-center gap-1 group">
                        <span className="flex-1 text-xs font-mono text-zinc-400 truncate" title={s}>{s}</span>
                        <button
                          onClick={() => setSourceList(sourceList.filter(x => x !== s))}
                          className="text-neutral hover:text-danger text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                        >×</button>
                      </div>
                    ))}
                    {sourceList.length === 0 && <div className="text-xs text-neutral">No sources</div>}
                  </div>
                  <div className="flex gap-1">
                    <input
                      value={newSource}
                      onChange={e => setNewSource(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && addSource()}
                      placeholder="filename.jpg"
                      className="flex-1 bg-surface-2 border border-surface-3 rounded px-2 py-1 text-xs text-white placeholder-neutral focus:outline-none focus:border-primary font-mono"
                    />
                    <button onClick={addSource} className="px-2 py-1 bg-surface-3 hover:bg-surface-4 text-white rounded text-xs border border-surface-4">+</button>
                  </div>
                </div>

                <div className="text-xs text-neutral">
                  <span className="text-zinc-500">Created:</span> {item.createdAt || '—'}
                </div>
              </div>
            </section>

            <div className="border-t border-surface-3" />

            {/* Quality */}
            <section>
              <div className="flex items-center justify-between mb-2">
                <div className="section-title">Quality</div>
                <span className={cn('text-2xl font-bold tabular-nums leading-none', qColor)}>{quality}</span>
              </div>
              <input
                type="range" min={0} max={10} step={1}
                value={quality}
                onChange={e => setQuality(Number(e.target.value))}
                className="w-full accent-primary cursor-pointer"
              />
              <div className="flex justify-between text-xs text-neutral mt-1">
                <span>0</span><span>5</span><span>10</span>
              </div>
              {item.suggestedQuality !== null && (
                <div className="text-xs text-neutral mt-1.5">
                  AI suggests: <span className="text-warning font-medium">~{item.suggestedQuality}</span>
                </div>
              )}
              {quality > 0 && quality < 7 && (
                <div className="text-xs text-danger mt-1">Need ≥ 7 to promote</div>
              )}
            </section>

            <div className="border-t border-surface-3" />

            {/* Status */}
            <section>
              <div className="section-title mb-3">Status</div>
              <select
                value={status}
                onChange={e => setStatus(e.target.value as ReviewStatus)}
                className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-primary mb-2"
              >
                <option value="draft">draft</option>
                <option value="review">review</option>
                <option value="approved">approved</option>
                <option value="archived">archived</option>
              </select>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={reviewed}
                  onChange={e => setReviewed(e.target.checked)}
                  className="accent-primary w-4 h-4"
                />
                <span className="text-sm text-zinc-300">Marked reviewed</span>
              </label>
            </section>

            <div className="border-t border-surface-3" />

            {/* Tags */}
            <section>
              <div className="section-title mb-3">Tags</div>
              <div className="flex flex-wrap gap-1.5 mb-2 min-h-[24px]">
                {tags.map(t => (
                  <span key={t} className="badge bg-surface-3 text-zinc-300 border-surface-4 text-xs gap-1">
                    {t}
                    <button onClick={() => setTags(tags.filter(x => x !== t))} className="text-neutral hover:text-danger ml-0.5 leading-none">×</button>
                  </span>
                ))}
              </div>
              <div className="flex gap-1">
                <input
                  value={newTag}
                  onChange={e => setNewTag(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addTag()}
                  placeholder="Add tag…"
                  className="flex-1 bg-surface-2 border border-surface-3 rounded px-2 py-1 text-xs text-white placeholder-neutral focus:outline-none focus:border-primary"
                />
                <button onClick={addTag} className="px-2 py-1 bg-surface-3 hover:bg-surface-4 text-white rounded text-xs border border-surface-4">+</button>
              </div>
            </section>

            <div className="border-t border-surface-3" />

            {/* Relationships */}
            <section>
              <div className="flex items-center justify-between mb-3">
                <div className="section-title">Relationships</div>
                {item.isOrphan && <span className="text-danger text-xs font-medium">⚠ orphan</span>}
              </div>
              <div className="space-y-1 mb-2 min-h-[20px]">
                {relationships.map(r => (
                  <div key={r} className="flex items-center gap-1 group">
                    <span className="flex-1 text-xs font-mono text-primary truncate" title={r}>{r}</span>
                    <button onClick={() => setRels(relationships.filter(x => x !== r))} className="text-neutral hover:text-danger text-xs opacity-0 group-hover:opacity-100 transition-opacity shrink-0">×</button>
                  </div>
                ))}
                {relationships.length === 0 && <div className="text-xs text-neutral">No relationships</div>}
              </div>
              <div className="flex gap-1">
                <input
                  value={newRel}
                  onChange={e => setNewRel(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addRel()}
                  placeholder="[[entity-slug]]"
                  className="flex-1 bg-surface-2 border border-surface-3 rounded px-2 py-1 text-xs text-white placeholder-neutral focus:outline-none focus:border-primary font-mono"
                />
                <button onClick={addRel} className="px-2 py-1 bg-surface-3 hover:bg-surface-4 text-white rounded text-xs border border-surface-4">+</button>
              </div>
            </section>

            <div className="border-t border-surface-3" />

            {/* Re-process with agents */}
            <section>
              <div className="section-title mb-3">Re-process</div>
              {agentMsg && !runningAgent && (
                <div className={cn('text-xs mb-2 rounded px-2 py-1', agentMsg.ok ? 'text-success bg-success/10' : 'text-danger bg-danger/10')}>
                  {agentMsg.ok ? '✓' : '✗'} {agentMsg.text}
                </div>
              )}
              <div className="grid grid-cols-2 gap-1.5">
                {agents.filter(a => REPROCESS_AGENTS.includes(a.id)).map(agent => {
                  const label = AGENT_LABELS[agent.id] ?? agent.id
                  const hasNote = !!agentNotes[agent.id]
                  return (
                    <button
                      key={agent.id}
                      onClick={() => openAgentDialog(agent.id, label, agent.description)}
                      disabled={!!runningAgent}
                      title={hasNote ? `${agent.description}\n\nNote: ${agentNotes[agent.id]}` : agent.description}
                      className={cn(
                        'px-2 py-1.5 rounded text-xs font-medium border transition-colors text-left relative',
                        'bg-surface-2 border-surface-3 text-zinc-300 hover:bg-surface-3 hover:border-surface-4',
                        runningAgent && 'opacity-40 cursor-not-allowed'
                      )}
                    >
                      {label}
                      {hasNote && (
                        <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-primary" title="Has note" />
                      )}
                    </button>
                  )
                })}
              </div>
            </section>

          </div>
        </div>
      </div>
    </div>
  )
}
