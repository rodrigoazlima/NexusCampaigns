'use client'

import { useState, useCallback, useEffect, useRef, type ReactNode } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import {
  ArrowLeft, CheckCircle, Archive, XCircle, Flag,
  Loader2, Maximize2, Upload, RefreshCw, ImagePlus, FileText, ChevronRight,
  Pencil, Check, X, Sparkles, ChevronDown, Save
} from 'lucide-react'
import type { ItemDetail } from '@/lib/types'
import QualityPicker from './QualityPicker'
import ImageModal from './ImageModal'
import TagEditor from './TagEditor'
import RelationshipEditor from './RelationshipEditor'
import ItemChatPanel from './ItemChatPanel'
import { Tip } from './Tip'

import '@uiw/react-md-editor/markdown-editor.css'
import '@uiw/react-markdown-preview/markdown.css'

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false })
const MarkdownPreview = dynamic(() => import('@uiw/react-markdown-preview'), { ssr: false })

// Split a vault md file into its YAML frontmatter block and the body below it.
// Tolerant of CRLF — vault files are written on Windows.
function splitFrontmatter(raw: string): { fm: string; body: string } {
  const m = raw.match(/^(---\r?\n[\s\S]*?\r?\n---\r?\n?)([\s\S]*)$/)
  return m ? { fm: m[1], body: m[2] } : { fm: '', body: raw }
}

// Smart icon action button with tooltip + color variant
function ActionBtn({
  onClick, disabled, label, side = 'bottom', children, variant = 'ghost', busy = false,
}: {
  onClick?: () => void
  disabled?: boolean
  label: string
  side?: 'top' | 'bottom' | 'left' | 'right'
  children: ReactNode
  variant?: 'ghost' | 'success' | 'danger' | 'warning' | 'primary'
  busy?: boolean
}) {
  const v = {
    ghost:   'border-surface-3 bg-surface-2 text-zinc-400 hover:border-zinc-600 hover:text-zinc-100',
    success: 'border-success/40 bg-success/10 text-success hover:bg-success/20',
    danger:  'border-danger/40 bg-danger/10 text-danger hover:bg-danger/20',
    warning: 'border-warning/40 bg-warning/10 text-warning hover:bg-warning/20',
    primary: 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/20',
  }[variant]
  return (
    <Tip label={label} side={side}>
      <button
        onClick={onClick}
        disabled={disabled}
        className={`inline-flex items-center justify-center w-8 h-8 rounded-lg border transition-all ${v} ${disabled ? 'opacity-30 !cursor-not-allowed' : 'cursor-pointer'}`}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : children}
      </button>
    </Tip>
  )
}

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

const STATUS_COLORS: Record<string, string> = {
  approved: 'bg-success/10 text-success',
  rejected: 'bg-danger/10 text-danger',
  archived: 'bg-zinc-700 text-zinc-500',
  review: 'bg-warning/10 text-warning',
  draft: 'bg-zinc-700 text-zinc-400',
}

// Native select styled as an inline colored badge
function BadgeSelect({
  value, options, onChange, colorClass,
}: {
  value: string
  options: string[]
  onChange: (v: string) => void
  colorClass: string
}) {
  return (
    <div className={`relative inline-flex items-center rounded ${colorClass}`}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="appearance-none bg-transparent text-[10px] font-semibold uppercase tracking-wide pl-1.5 pr-5 py-0.5 outline-none cursor-pointer"
      >
        {options.map((o) => (
          <option key={o} value={o} className="bg-surface-2 text-zinc-200 normal-case">{o}</option>
        ))}
      </select>
      <ChevronDown size={11} className="absolute right-1 pointer-events-none opacity-60" />
    </div>
  )
}

interface Toast { message: string; type: 'success' | 'error' }

interface Props { item: ItemDetail }

export default function ItemDetailView({ item: initial }: Props) {
  const router = useRouter()
  const [item, setItem] = useState<ItemDetail>(initial)
  const [toast, setToast] = useState<Toast | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [uploadingImage, setUploadingImage] = useState(false)
  const [uploadingBase, setUploadingBase] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [modalSrc, setModalSrc] = useState<string | null>(null)
  const [renameInput, setRenameInput] = useState(item.id)
  const [editingName, setEditingName] = useState(false)
  const [showApproveQuality, setShowApproveQuality] = useState(false)
  const [approveQuality, setApproveQuality] = useState<number | null>(item.quality || null)
  const [mdContent, setMdContent] = useState<string | null>(null)
  const [body, setBody] = useState('')
  const [bodyDirty, setBodyDirty] = useState(false)
  const [savingContent, setSavingContent] = useState(false)
  const [contentEditMode, setContentEditMode] = useState(false)
  const [showEditHint, setShowEditHint] = useState(false)
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    fetch(`/api/gm/content?filename=${encodeURIComponent(item.filename)}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.content) {
          setMdContent(d.content)
          setBody(splitFrontmatter(d.content).body)
          setBodyDirty(false)
        }
      })
      .catch(() => {})
  }, [item.filename])

  const imageSrc = item.source[0]
    ? `/api/image?path=${encodeURIComponent(item.source[0])}`
    : null

  const tokenSrc = item.tokenPath
    ? `/api/image?path=${encodeURIComponent(item.tokenPath)}${item.tokenUpdatedAt ? `&v=${encodeURIComponent(item.tokenUpdatedAt)}` : ''}`
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
        router.push(`/gm/view/${item.uuid || data.newFilename.replace('.md', '')}`)
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

  const handleReplaceImage = async (file: File) => {
    if (!item.source[0]) return
    setUploadingImage(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('targetPath', item.source[0])
      const res = await fetch('/api/gm/upload-image', { method: 'POST', body: form })
      const data = await res.json()
      if (data.ok) {
        showToast('Image replaced', 'success')
        // Force re-render by appending cache-buster to image src
        setItem((i) => ({ ...i }))
      } else {
        showToast(data.error ?? 'Upload failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setUploadingImage(false)
    }
  }

  const handleUploadTokenBase = async (file: File) => {
    if (!item.source[0]) return
    setUploadingBase(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('sourcePath', item.source[0])
      const res = await fetch('/api/gm/token/upload-base', { method: 'POST', body: form })
      const data = await res.json()
      if (data.ok) {
        router.push(`/gm/view/${item.uuid || item.id}/token`)
      } else {
        showToast(data.error ?? 'Upload failed', 'error')
        setUploadingBase(false)
      }
    } catch (err) {
      showToast(String(err), 'error')
      setUploadingBase(false)
    }
  }

  // Save the edited body. Re-fetch the file first so frontmatter edited via the
  // rail (type/status/quality/tags) isn't clobbered by a stale copy.
  const handleSaveContent = async () => {
    setSavingContent(true)
    try {
      const fresh = await fetch(`/api/gm/content?filename=${encodeURIComponent(item.filename)}`).then((r) => r.json())
      const fm = splitFrontmatter(fresh.content ?? mdContent ?? '').fm
      const newRaw = fm + body
      const res = await fetch('/api/gm/content', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: item.filename, content: newRaw }),
      })
      const data = await res.json()
      if (!data.ok) throw new Error(data.error ?? 'Save failed')
      setMdContent(newRaw)
      setBodyDirty(false)
      setContentEditMode(false)
      showToast('Content saved', 'success')
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setSavingContent(false)
    }
  }

  const canToken = item.tokenEligible || !!tokenSrc

  return (
    <div className="min-h-screen flex flex-col">
      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-4 py-2 rounded-full border shadow-2xl backdrop-blur-sm text-sm font-medium ${
          toast.type === 'success'
            ? 'bg-success/10 border-success/40 text-success'
            : 'bg-danger/10 border-danger/40 text-danger'
        }`}>
          {toast.type === 'success' ? <Check size={14} /> : <X size={14} />}
          {toast.message}
        </div>
      )}

      {/* ── Sticky header ── */}
      <header className="sticky top-0 z-30 bg-surface-1/95 backdrop-blur border-b border-surface-3 px-4 md:px-6 py-2.5 flex items-center gap-2 flex-wrap">
        <Link
          href="/gm/review"
          className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300 transition-colors shrink-0"
        >
          <ArrowLeft size={14} /> back
        </Link>
        <span className="text-surface-4">/</span>

        {/* id + inline rename */}
        {editingName ? (
          <div className="flex items-center gap-1">
            <input
              autoFocus
              value={renameInput}
              onChange={(e) => setRenameInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRename()
                if (e.key === 'Escape') { setEditingName(false); setRenameInput(item.id) }
              }}
              className="bg-surface-3 border border-primary/40 text-zinc-100 text-sm rounded px-2 py-1 outline-none font-mono w-56"
              placeholder="new-slug"
            />
            <ActionBtn
              label="Confirm rename" variant="success" busy={loading}
              disabled={loading || !renameInput.trim() || renameInput.trim() === item.id}
              onClick={handleRename}
            ><Check size={14} /></ActionBtn>
            <ActionBtn
              label="Cancel" variant="ghost"
              onClick={() => { setEditingName(false); setRenameInput(item.id) }}
            ><X size={14} /></ActionBtn>
          </div>
        ) : (
          <button
            onClick={() => { setRenameInput(item.id); setEditingName(true) }}
            className="group flex items-center gap-1.5 font-mono text-sm font-semibold text-zinc-100 hover:text-white transition-colors"
            title="Rename"
          >
            {item.id}
            <Pencil size={12} className="opacity-0 group-hover:opacity-60 transition-opacity" />
          </button>
        )}

        {/* type / status as inline editable badges */}
        <BadgeSelect
          value={item.type}
          options={ENTITY_TYPES}
          onChange={handleTypeChange}
          colorClass={TYPE_COLORS[item.type] ?? 'bg-zinc-700 text-zinc-400'}
        />
        <BadgeSelect
          value={item.status}
          options={ENTITY_STATUSES}
          onChange={handleStatusChange}
          colorClass={STATUS_COLORS[item.status] ?? 'bg-zinc-700 text-zinc-400'}
        />
        {item.reviewed && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-semibold uppercase">
            reviewed
          </span>
        )}

        <div className="flex-1" />

        {/* action buttons */}
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={handlePromote}
            disabled={loading || (showApproveQuality && approveQuality === null)}
            className="flex items-center gap-1.5 h-8 px-3 text-xs font-medium rounded-lg bg-success/10 text-success border border-success/40 hover:bg-success/20 transition-colors disabled:opacity-40"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
            {showApproveQuality ? (approveQuality !== null ? `Promote (${approveQuality})` : 'Pick score') : 'Promote'}
          </button>
          {showApproveQuality && (
            <ActionBtn
              label="Cancel promote" variant="ghost"
              onClick={() => { setShowApproveQuality(false); setApproveQuality(item.quality || null) }}
            ><X size={14} /></ActionBtn>
          )}
          <ActionBtn label="Flag for reprocessing" variant="warning" disabled={loading} onClick={handleFlag}>
            <Flag size={14} />
          </ActionBtn>
          <ActionBtn label="Archive to 99-Archive" variant="ghost" disabled={loading} onClick={handleArchive}>
            <Archive size={14} />
          </ActionBtn>
          <ActionBtn label="Reject (quality → 1)" variant="danger" disabled={loading} onClick={handleReject}>
            <XCircle size={14} />
          </ActionBtn>
        </div>
      </header>

      {/* promote quality picker drops below header */}
      {showApproveQuality && (
        <div className="bg-surface-1 border-b border-surface-3 px-4 md:px-6 py-3 flex items-center gap-3">
          <span className="text-[11px] text-zinc-500 uppercase tracking-wide shrink-0">Quality to promote</span>
          <QualityPicker value={approveQuality} onChange={setApproveQuality} />
        </div>
      )}

      {/* ── Body ── */}
      <div className="flex-1 p-4 md:p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* LEFT: integrated media */}
        <div className="space-y-4">

          {/* Hero — source image with token integrated */}
          <div className="relative group rounded-2xl overflow-hidden bg-surface-2 border border-surface-3 flex items-center justify-center" style={{ minHeight: 720 }}>
            {imageSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={imageSrc}
                alt={item.id}
                className="max-h-[60vh] w-full object-contain cursor-zoom-in"
                onClick={() => { setModalSrc(imageSrc); setModalOpen(true) }}
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
              />
            ) : tokenSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={tokenSrc} alt={item.id}
                className="max-h-[50vh] max-w-[60%] object-contain cursor-zoom-in"
                onClick={() => { setModalSrc(tokenSrc); setModalOpen(true) }}
              />
            ) : (
              <div className="text-zinc-600 text-sm py-20">No image</div>
            )}

            {/* hover toolbar */}
            <div className="absolute top-2 right-2 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
              {imageSrc && (
                <ActionBtn label="Enlarge" variant="ghost" side="left"
                  onClick={() => { setModalSrc(imageSrc); setModalOpen(true) }}
                ><Maximize2 size={14} /></ActionBtn>
              )}
              {item.source[0] && (
                <label className="inline-flex">
                  <input
                    type="file"
                    accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tiff,.tif,.avif,.heic,.heif,.jfif"
                    className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleReplaceImage(f); e.target.value = '' }}
                    disabled={uploadingImage}
                  />
                  <Tip label="Replace source image" side="left">
                    <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg border border-surface-3 bg-surface-2/90 text-zinc-400 hover:border-zinc-600 hover:text-zinc-100 cursor-pointer transition-all">
                      {uploadingImage ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                    </span>
                  </Tip>
                </label>
              )}
            </div>

            {/* integrated token companion (bottom-right) */}
            {item.source[0] && (
              <div className="absolute bottom-3 right-3 z-20">
                {tokenSrc ? (
                  <Link
                    href={`/gm/view/${item.uuid || item.id}/token`}
                    className="relative block w-24 h-24 rounded-full overflow-hidden border-2 border-zinc-700/70 shadow-2xl hover:border-primary/60 hover:scale-105 transition-all group/token bg-surface"
                    title="Open token editor"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={tokenSrc} alt="token" className="w-full h-full object-contain" />
                    <span className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover/token:opacity-100 transition-opacity">
                      <Pencil size={16} className="text-white" />
                    </span>
                  </Link>
                ) : canToken ? (
                  <Tip label="Generate token" side="left">
                    <button
                      onClick={handleGenerateToken}
                      disabled={generating}
                      className="w-24 h-24 rounded-full border-2 border-dashed border-surface-4 flex flex-col items-center justify-center bg-surface/80 backdrop-blur text-zinc-500 hover:text-primary hover:border-primary/50 transition-all disabled:opacity-50"
                    >
                      {generating ? <Loader2 size={20} className="animate-spin" /> : <Sparkles size={20} />}
                      <span className="text-[9px] mt-1 uppercase tracking-wide">token</span>
                    </button>
                  </Tip>
                ) : null}
              </div>
            )}

            {/* classification pills (bottom-left) */}
            {item.imageClassification && (
              <div className="absolute bottom-3 left-3 flex flex-wrap gap-1 max-w-[60%] opacity-0 group-hover:opacity-100 transition-opacity">
                {(['type','ancestry','char_class','element','environment'] as const).map((field) => {
                  const cls = item.imageClassification!
                  const val = cls[field as keyof typeof cls] as string | undefined
                  if (!val || val === 'none') return null
                  return (
                    <span key={field} className="text-[10px] px-1.5 py-0.5 rounded bg-black/60 backdrop-blur text-zinc-300 font-mono">
                      {field}: {val}
                    </span>
                  )
                })}
              </div>
            )}
          </div>

          {/* Token toolbar */}
          <div className="panel p-3 flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 mr-1">Token</span>
            {canToken && (
              <button
                onClick={handleGenerateToken}
                disabled={generating || !item.source[0]}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors disabled:opacity-50"
              >
                {generating ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                {tokenSrc ? 'Regenerate' : 'Generate'}
              </button>
            )}
            {item.source[0] && (
              <Link
                href={`/gm/view/${item.uuid || item.id}/token`}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-surface-3 text-zinc-300 border border-surface-3 hover:border-zinc-600 hover:text-white transition-colors"
              >
                <Pencil size={13} /> Edit
              </Link>
            )}
            {item.source[0] && (
              <label className="inline-flex">
                <input
                  type="file"
                  accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tiff,.tif,.avif,.heic,.heif,.jfif"
                  className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUploadTokenBase(f); e.target.value = '' }}
                  disabled={uploadingBase}
                />
                <Tip label="Upload custom base image for the token">
                  <span className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg bg-surface-3 text-zinc-300 border border-surface-3 hover:border-zinc-600 hover:text-white transition-colors cursor-pointer">
                    {uploadingBase ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
                    Base
                  </span>
                </Tip>
              </label>
            )}
            {!canToken && (
              <span className="text-xs text-zinc-600 italic">
                Portrait/body types only
                {item.imageClassification && ` · this: ${item.imageClassification.type}`}
              </span>
            )}
            {item.source[0] && (
              <span className="ml-auto text-[10px] text-zinc-600 font-mono truncate max-w-[200px]" title={item.source[0]}>
                {item.source[0].split('/').pop()}
              </span>
            )}
          </div>
        </div>

        {/* RIGHT: content editor — narrative body (history, lore, location, gods, …) */}
        {mdContent !== null && (
          <div className="space-y-4">
            <div className="panel p-4">
              <div className="flex items-center gap-2 mb-3">
                <FileText size={13} className="text-zinc-500" />
                <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Content</span>
                {bodyDirty && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-warning/10 text-warning font-medium">unsaved</span>
                )}
                <div className="flex-1" />
                {contentEditMode && (
                  <button
                    onClick={handleSaveContent}
                    disabled={savingContent || !bodyDirty}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-success/10 text-success border border-success/40 hover:bg-success/20 transition-colors disabled:opacity-40"
                  >
                    {savingContent ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    {savingContent ? 'Saving…' : 'Save Content'}
                  </button>
                )}
              </div>
              <div
                className="relative"
                onMouseEnter={() => {
                  if (contentEditMode) return
                  hoverTimerRef.current = setTimeout(() => setShowEditHint(true), 3000)
                }}
                onMouseLeave={() => {
                  if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
                  setShowEditHint(false)
                }}
              >
                <div data-color-mode="dark">
                  {contentEditMode ? (
                    <MDEditor
                      value={body}
                      onChange={(v) => { setBody(v ?? ''); setBodyDirty(true) }}
                      height={720}
                      visibleDragbar={false}
                      textareaProps={{ placeholder: 'Add history, name, location, lore, gods, abilities…' }}
                    />
                  ) : (
                    <div
                      onDoubleClick={() => setContentEditMode(true)}
                      className="min-h-[720px] px-1 cursor-text"
                    >
                      <MarkdownPreview source={body || '*No content yet — double click to edit*'} />
                    </div>
                  )}
                </div>
                {!contentEditMode && showEditHint && (
                  <button
                    onClick={() => setContentEditMode(true)}
                    className="absolute bottom-3 right-3 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary/10 text-primary border border-primary/40 hover:bg-primary/20 shadow-lg transition-colors"
                  >
                    <Pencil size={13} /> Edit
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* metadata rail — full width */}
      <div className="px-4 md:px-6 pb-4">
        <div className="panel p-4 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-2">Tags</label>
            <TagEditor tags={item.tags} onChange={handleTagsChange} />
          </div>

          <div>
            <label className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 block mb-2">Relationships</label>
            <RelationshipEditor relationships={item.relationships} onChange={handleRelsChange} />
          </div>

          <div className="text-[10px] text-zinc-600 space-y-0.5 md:pt-5">
            <div>Created: {item.created}</div>
            <div>Updated: {item.updated}</div>
            <div className="font-mono truncate" title={item.filename}>{item.filename}</div>
          </div>
        </div>
      </div>

      {/* Linked drafts */}
      {item.history.length > 0 && (
        <div className="px-4 md:px-6 pb-4">
          <div className="panel p-4">
            <div className="flex items-center gap-2 mb-3">
              <FileText size={13} className="text-zinc-500" />
              <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Linked Drafts · same source</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-3 text-zinc-500 font-mono">{item.history.length}</span>
            </div>
            <div className="space-y-1.5">
              {item.history.map((h) => (
                <Link
                  key={h.id}
                  href={`/gm/view/${h.uuid || h.id}`}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-3 border border-surface-3 hover:border-primary/30 transition-colors group"
                >
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${TYPE_COLORS[h.type] ?? 'bg-zinc-700 text-zinc-400'}`}>
                    {h.type}
                  </span>
                  <span className="font-mono text-xs text-zinc-300 truncate flex-1">{h.id}</span>
                  {h.reviewed && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-semibold uppercase">reviewed</span>
                  )}
                  <ChevronRight size={14} className="text-zinc-600 group-hover:text-primary transition-colors" />
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Chat panel */}
      <div className="px-4 md:px-6 pb-6">
        <ItemChatPanel item={item} agents={item.activeAgents} />
      </div>

      {/* Image modal */}
      {(modalSrc ?? imageSrc) && (
        <ImageModal
          src={modalSrc ?? imageSrc!}
          alt={item.id}
          open={modalOpen}
          onClose={() => { setModalOpen(false); setModalSrc(null) }}
        />
      )}
    </div>
  )
}
