'use client'

import { useState, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  ArrowLeft, CheckCircle, Archive, XCircle, Flag,
  Loader2, CircleDot, ZoomIn
} from 'lucide-react'
import type { ItemDetail } from '@/lib/types'
import QualityBar from '@/components/widgets/QualityBar'
import QualityPicker from './QualityPicker'
import ImageModal from './ImageModal'
import TagEditor from './TagEditor'
import RelationshipEditor from './RelationshipEditor'
import ItemChatPanel from './ItemChatPanel'

const ENTITY_TYPES = [
  'npc','character','faction','location','city','village','dungeon',
  'item','artifact','quest','encounter','creature','monster','event',
  'religion','organization','timeline','lore',
]

const ENTITY_STATUSES = ['draft', 'review', 'approved', 'archived']

const TYPE_COLORS: Record<string, string> = {
  npc: 'bg-blue-500/10 text-blue-400',
  character: 'bg-blue-500/10 text-blue-400',
  location: 'bg-green-500/10 text-green-400',
  faction: 'bg-purple-500/10 text-purple-400',
  quest: 'bg-yellow-500/10 text-yellow-400',
  creature: 'bg-red-500/10 text-red-400',
  item: 'bg-orange-500/10 text-orange-400',
  lore: 'bg-teal-500/10 text-teal-400',
}

interface Toast { message: string; type: 'success' | 'error' }

interface Props { item: ItemDetail }

export default function ItemDetailView({ item: initial }: Props) {
  const router = useRouter()
  const [item, setItem] = useState<ItemDetail>(initial)
  const [toast, setToast] = useState<Toast | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [renameInput, setRenameInput] = useState(item.id)
  const [showApproveQuality, setShowApproveQuality] = useState(false)
  const [approveQuality, setApproveQuality] = useState<number | null>(item.quality || null)

  const imageSrc = item.source[0]
    ? `/api/image?path=${encodeURIComponent(item.source[0])}`
    : null

  const tokenSrc = item.tokenPath
    ? `/api/image?path=${encodeURIComponent(item.tokenPath)}`
    : null

  const showToast = useCallback((message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }, [])

  const apiPost = async (url: string, body: Record<string, unknown>) => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return res.json()
  }

  const saveField = async (fields: Record<string, unknown>) => {
    try {
      const data = await apiPost('/api/gm/edit', { filename: item.filename, fields })
      if (!data.ok) throw new Error(data.error ?? 'Save failed')
    } catch (err) {
      showToast(String(err), 'error')
    }
  }

  const handleTypeChange = async (newType: string) => {
    setItem((i) => ({ ...i, type: newType }))
    await saveField({ type: newType })
  }

  const handleStatusChange = async (newStatus: string) => {
    setItem((i) => ({ ...i, status: newStatus }))
    await saveField({ status: newStatus })
  }

  const handleQualityChange = async (q: number) => {
    setItem((i) => ({ ...i, quality: q }))
    await saveField({ quality: q })
    showToast(`Quality set to ${q}`, 'success')
  }

  const handleTagsChange = async (tags: string[]) => {
    setItem((i) => ({ ...i, tags }))
    await saveField({ tags })
  }

  const handleRelsChange = async (rels: string[]) => {
    setItem((i) => ({ ...i, relationships: rels }))
    await saveField({ relationships: rels })
  }

  const handleRename = async () => {
    if (!renameInput.trim() || renameInput.trim() === item.id) return
    setLoading(true)
    try {
      const data = await apiPost('/api/gm/rename', {
        filename: item.filename,
        newSlug: renameInput.trim(),
      })
      if (data.ok) {
        showToast('Renamed successfully', 'success')
        router.push(`/gm/view/${data.newFilename.replace('.md', '')}`)
      } else {
        showToast(data.error ?? 'Rename failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setLoading(false)
    }
  }

  const handlePromote = async () => {
    if (!showApproveQuality) { setShowApproveQuality(true); return }
    if (approveQuality === null) return
    setLoading(true)
    try {
      const data = await apiPost('/api/gm/approve', { filename: item.filename, quality: approveQuality })
      if (data.ok) {
        showToast('Promoted to Library', 'success')
        router.push('/gm/review')
      } else {
        showToast(data.error ?? 'Promote failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleArchive = async () => {
    if (!confirm(`Archive "${item.id}"? It will be moved to 99-Archive.`)) return
    setLoading(true)
    try {
      const data = await apiPost('/api/gm/archive', { filename: item.filename })
      if (data.ok) {
        showToast('Archived', 'success')
        router.push('/gm/review')
      } else {
        showToast(data.error ?? 'Archive failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleReject = async () => {
    if (!confirm(`Reject "${item.id}"? Quality will be set to 1.`)) return
    setLoading(true)
    try {
      const data = await apiPost('/api/gm/reject', { filename: item.filename })
      if (data.ok) {
        showToast('Rejected', 'success')
        setItem((i) => ({ ...i, status: 'rejected', quality: 1 }))
      } else {
        showToast(data.error ?? 'Reject failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleFlag = async () => {
    setLoading(true)
    try {
      const data = await apiPost('/api/gm/flag', { filename: item.filename })
      if (data.ok) {
        showToast('Flagged for reprocessing', 'success')
      } else {
        showToast(data.error ?? 'Flag failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleGenerateToken = async () => {
    if (!item.source[0]) return
    setGenerating(true)
    try {
      const imagePath = item.source[0]
      const data = await apiPost('/api/gm/token/generate', { imagePath })
      if (data.ok) {
        showToast('Token generated', 'success')
        setItem((i) => ({ ...i, tokenPath: data.tokenPath }))
      } else {
        showToast(data.error ?? 'Token generation failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setGenerating(false)
    }
  }

  const typeBadgeClass = TYPE_COLORS[item.type] ?? 'bg-zinc-700 text-zinc-400'
  const statusBadgeClass =
    item.status === 'approved' ? 'bg-success/10 text-success' :
    item.status === 'rejected' ? 'bg-danger/10 text-danger' :
    item.status === 'archived' ? 'bg-zinc-700 text-zinc-500' :
    'bg-zinc-700 text-zinc-400'

  return (
    <div className="min-h-screen p-4 md:p-6">
      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm font-medium shadow-lg ${
          toast.type === 'success' ? 'bg-success text-white' : 'bg-danger text-white'
        }`}>
          {toast.message}
        </div>
      )}

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-zinc-500 mb-4">
        <Link href="/gm" className="hover:text-zinc-300 transition-colors">GM Hub</Link>
        <span>/</span>
        <Link href="/gm/review" className="hover:text-zinc-300 transition-colors">Review Queue</Link>
        <span>/</span>
        <span className="text-zinc-300 font-mono">{item.id}</span>
      </div>

      {/* Header */}
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <Link
          href="/gm/review"
          className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          <ArrowLeft size={14} />
          Back
        </Link>
        <h1 className="font-mono text-lg font-semibold text-zinc-100">{item.id}</h1>
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${typeBadgeClass}`}>
          {item.type}
        </span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${statusBadgeClass}`}>
          {item.status}
        </span>
        {item.reviewed && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-semibold uppercase">
            reviewed
          </span>
        )}
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 mb-6">
        {/* LEFT: Media */}
        <div className="lg:col-span-3 space-y-4">
          {/* Source image */}
          <div className="panel p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">Source Image</div>
            {imageSrc ? (
              <div className="relative group">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imageSrc}
                  alt={item.id}
                  className="w-full max-h-80 object-contain rounded-lg bg-surface-3 cursor-zoom-in"
                  onClick={() => setModalOpen(true)}
                  onError={(e) => {
                    const t = e.currentTarget
                    t.parentElement!.innerHTML =
                      '<div class="w-full h-32 flex items-center justify-center text-zinc-600 text-xs bg-surface-3 rounded-lg">Image not found</div>'
                  }}
                />
                <button
                  onClick={() => setModalOpen(true)}
                  className="absolute top-2 right-2 p-1.5 bg-black/60 rounded text-zinc-300 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <ZoomIn size={14} />
                </button>
              </div>
            ) : (
              <div className="w-full h-32 flex items-center justify-center text-zinc-600 text-xs bg-surface-3 rounded-lg">
                No image
              </div>
            )}
            {item.source.length > 0 && (
              <div className="mt-2 text-[10px] text-zinc-600 font-mono truncate" title={item.source[0]}>
                {item.source[0]}
              </div>
            )}
            {item.imageClassification && (
              <div className="mt-2 flex flex-wrap gap-1">
                {(['type','ancestry','char_class','element','environment'] as const).map((field) => {
                  const cls = item.imageClassification!
                  const val = cls[field as keyof typeof cls] as string | undefined
                  if (!val || val === 'none') return null
                  return (
                    <span key={field} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-zinc-500 font-mono">
                      {field}: {val}
                    </span>
                  )
                })}
              </div>
            )}
          </div>

          {/* Token panel */}
          <div className="panel p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-3">Token</div>
            {tokenSrc ? (
              <div className="flex items-center gap-4">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={tokenSrc}
                  alt={`${item.id} token`}
                  className="w-24 h-24 object-contain rounded-full border border-surface-3"
                />
                <div className="text-xs text-zinc-500">
                  <div className="text-zinc-300 font-mono mb-1">{item.tokenPath?.split('/').pop()}</div>
                  <div>Token generated</div>
                  {item.tokenEligible && (
                    <button
                      onClick={handleGenerateToken}
                      disabled={generating}
                      className="mt-2 flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-surface-3 text-zinc-400 hover:text-zinc-200 transition-colors disabled:opacity-50"
                    >
                      {generating ? <Loader2 size={11} className="animate-spin" /> : <CircleDot size={11} />}
                      Regenerate
                    </button>
                  )}
                </div>
              </div>
            ) : item.tokenEligible ? (
              <div className="flex items-center gap-3">
                <div className="w-24 h-24 rounded-full border border-dashed border-surface-3 flex items-center justify-center bg-surface-3">
                  <CircleDot size={22} className="text-zinc-600" />
                </div>
                <div>
                  <div className="text-xs text-zinc-400 mb-2">No token yet</div>
                  <button
                    onClick={handleGenerateToken}
                    disabled={generating || !item.source[0]}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors disabled:opacity-50"
                  >
                    {generating ? <Loader2 size={13} className="animate-spin" /> : <CircleDot size={13} />}
                    Generate Token
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-xs text-zinc-600 italic">
                Tokens available for portrait/body images only
                {item.imageClassification && ` (this: ${item.imageClassification.type})`}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT: Metadata + Actions */}
        <div className="lg:col-span-2 space-y-4">
          <div className="panel p-4 space-y-4">
            {/* Type */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-1">Type</label>
              <select
                value={item.type}
                onChange={(e) => handleTypeChange(e.target.value)}
                className="w-full bg-surface-3 border border-surface-3 focus:border-primary/40 text-zinc-200 text-xs rounded px-2 py-1.5 outline-none transition-colors"
              >
                {ENTITY_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>

            {/* Status */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-1">Status</label>
              <select
                value={item.status}
                onChange={(e) => handleStatusChange(e.target.value)}
                className="w-full bg-surface-3 border border-surface-3 focus:border-primary/40 text-zinc-200 text-xs rounded px-2 py-1.5 outline-none transition-colors"
              >
                {ENTITY_STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            {/* Quality */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-2">Quality</label>
              <div className="mb-2">
                <QualityBar score={item.quality} />
              </div>
              <QualityPicker
                value={item.quality || null}
                onChange={handleQualityChange}
              />
            </div>

            {/* Tags */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-2">Tags</label>
              <TagEditor tags={item.tags} onChange={handleTagsChange} />
            </div>

            {/* Relationships */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-2">Relationships</label>
              <RelationshipEditor relationships={item.relationships} onChange={handleRelsChange} />
            </div>

            {/* Rename */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-1">Rename (slug)</label>
              <div className="flex gap-2">
                <input
                  value={renameInput}
                  onChange={(e) => setRenameInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleRename() }}
                  className="flex-1 bg-surface-3 border border-surface-3 focus:border-primary/40 text-zinc-200 text-xs rounded px-2 py-1.5 outline-none transition-colors font-mono"
                  placeholder="new-slug"
                />
                <button
                  onClick={handleRename}
                  disabled={loading || !renameInput.trim() || renameInput.trim() === item.id}
                  className="px-2 py-1.5 text-xs rounded bg-surface-3 text-zinc-400 hover:text-zinc-200 border border-surface-3 hover:border-zinc-600 transition-colors disabled:opacity-40"
                >
                  Rename
                </button>
              </div>
            </div>

            {/* Meta */}
            <div className="text-[10px] text-zinc-600 space-y-0.5 pt-1 border-t border-surface-3">
              <div>Created: {item.created}</div>
              <div>Updated: {item.updated}</div>
              <div className="font-mono truncate" title={item.filename}>{item.filename}</div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="panel p-4 space-y-3">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 mb-2">Actions</div>

            {showApproveQuality && (
              <div className="p-3 bg-surface-3 rounded-lg border border-surface-3">
                <div className="text-[10px] text-zinc-500 mb-2">Select quality score to promote:</div>
                <QualityPicker value={approveQuality} onChange={setApproveQuality} />
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <button
                onClick={handlePromote}
                disabled={loading || (showApproveQuality && approveQuality === null)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-success/10 text-success border border-success/30 hover:bg-success/20 transition-colors disabled:opacity-50"
              >
                {loading ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                {showApproveQuality ? (approveQuality !== null ? `Promote (${approveQuality})` : 'Pick score…') : 'Promote to Library'}
              </button>

              {showApproveQuality && (
                <button
                  onClick={() => { setShowApproveQuality(false); setApproveQuality(item.quality || null) }}
                  className="px-3 py-1.5 text-xs rounded bg-surface-3 text-zinc-400 hover:text-zinc-200 transition-colors"
                >
                  Cancel
                </button>
              )}

              <button
                onClick={handleArchive}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-zinc-700/50 text-zinc-400 border border-zinc-700 hover:bg-zinc-700 transition-colors disabled:opacity-50"
              >
                <Archive size={13} />
                Archive
              </button>

              <button
                onClick={handleReject}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-danger/10 text-danger border border-danger/30 hover:bg-danger/20 transition-colors disabled:opacity-50"
              >
                <XCircle size={13} />
                Reject
              </button>

              <button
                onClick={handleFlag}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 transition-colors disabled:opacity-50"
              >
                <Flag size={13} />
                Flag Reprocess
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Chat panel */}
      {item.activeAgents.length > 0 && (
        <ItemChatPanel item={item} agents={item.activeAgents} />
      )}

      {/* Excerpt */}
      {item.excerpt && (
        <div className="panel p-4 mt-4">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 mb-2">Content Preview</div>
          <p className="text-xs text-zinc-400 leading-relaxed">{item.excerpt}</p>
        </div>
      )}

      {/* Image modal */}
      {imageSrc && (
        <ImageModal
          src={imageSrc}
          alt={item.id}
          open={modalOpen}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  )
}
