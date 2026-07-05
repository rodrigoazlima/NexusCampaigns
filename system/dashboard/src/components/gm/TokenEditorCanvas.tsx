'use client'

import { useRef, useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import type { ItemDetail } from '@/lib/types'
import { Tip } from './Tip'

interface Frame { name: string; url: string }

interface Props {
  item: ItemDetail
  imageSrc: string | null
  tokenSrc: string | null
}

const CANVAS_SIZE = 512
const CLIP_RADIUS = 234
const DISPLAY_SIZE = 460

// ─── Icon Button ─────────────────────────────────────────────────────────────

function IconBtn({
  onClick,
  disabled,
  label,
  children,
  variant = 'ghost',
  side = 'top',
  shortcut,
  active = false,
  size = 'md',
}: {
  onClick?: () => void
  disabled?: boolean
  label: string
  children: React.ReactNode
  variant?: 'ghost' | 'success' | 'star'
  side?: 'top' | 'bottom' | 'left' | 'right'
  shortcut?: string
  active?: boolean
  size?: 'sm' | 'md'
}) {
  const dim = size === 'sm' ? 'w-7 h-7' : 'w-8 h-8'
  const v = {
    ghost: active
      ? 'border-zinc-500 bg-zinc-600/80 text-white'
      : 'border-zinc-700/70 bg-zinc-900/80 text-zinc-400 hover:border-zinc-500 hover:bg-zinc-800 hover:text-zinc-100',
    success:
      'border-emerald-500/50 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 hover:text-emerald-300',
    star: active
      ? 'border-amber-400/60 bg-amber-400/15 text-amber-400'
      : 'border-zinc-700/70 bg-zinc-900/80 text-zinc-500 hover:border-amber-500/40 hover:text-amber-400',
  }[variant]

  return (
    <Tip label={label} side={side} shortcut={shortcut}>
      <button
        onClick={onClick}
        disabled={disabled}
        className={`inline-flex items-center justify-center ${dim} rounded-lg border backdrop-blur-sm transition-all text-[13px] leading-none select-none ${v} ${disabled ? 'opacity-30 !cursor-not-allowed' : 'cursor-pointer'}`}
      >
        {children}
      </button>
    </Tip>
  )
}

// ─── Divider ─────────────────────────────────────────────────────────────────

function Div() {
  return <div className="w-px h-4 bg-zinc-700/60 self-center mx-0.5" />
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function TokenEditorCanvas({ item, imageSrc, tokenSrc }: Props) {
  const router = useRouter()
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [frameIdx, setFrameIdx] = useState(0)
  const [frames, setFrames] = useState<Frame[]>([])
  const [defaultFrame, setDefaultFrame] = useState('')

  const srcImgRef = useRef<HTMLImageElement | null>(null)
  const frameImgRef = useRef<HTMLImageElement | null>(null)
  const [srcLoaded, setSrcLoaded] = useState(false)
  const [frameLoaded, setFrameLoaded] = useState(false)
  const [srcDims, setSrcDims] = useState<{ w: number; h: number } | null>(null)

  const dragging = useRef(false)
  const dragOrigin = useRef<{ mx: number; my: number; ox: number; oy: number } | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [savedTokenUrl, setSavedTokenUrl] = useState<string | null>(null)
  const [zoomVisible, setZoomVisible] = useState(false)
  const [tokenHovered, setTokenHovered] = useState(false)

  const saveTokenRef = useRef<() => Promise<boolean | void>>(async () => {})
  const saveAndReturnRef = useRef<() => Promise<void>>(async () => {})
  const initDone = useRef(false)
  const zoomTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const msgTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── helpers ──────────────────────────────────────────────────────────────

  const flashZoom = useCallback(() => {
    setZoomVisible(true)
    if (zoomTimer.current) clearTimeout(zoomTimer.current)
    zoomTimer.current = setTimeout(() => setZoomVisible(false), 1400)
  }, [])

  const showMsg = useCallback((text: string, ok: boolean) => {
    if (msgTimer.current) clearTimeout(msgTimer.current)
    setMsg({ text, ok })
    msgTimer.current = setTimeout(() => setMsg(null), 3000)
  }, [])

  // ── load frames ──────────────────────────────────────────────────────────

  useEffect(() => {
    fetch('/api/gm/token/frames')
      .then((r) => r.json())
      .then((data: { frames: Frame[]; defaultFrame: string }) => {
        setFrames(data.frames)
        setDefaultFrame(data.defaultFrame)
        const idx = data.frames.findIndex((f) => f.name === data.defaultFrame)
        if (idx >= 0) setFrameIdx(idx)
      })
      .catch(() => {})
  }, [])

  // ── load source image ────────────────────────────────────────────────────

  useEffect(() => {
    if (!imageSrc) return
    setSrcLoaded(false)
    const img = new Image()
    img.onload = () => {
      srcImgRef.current = img
      setSrcDims({ w: img.naturalWidth, h: img.naturalHeight })
      const cover = (CLIP_RADIUS * 2) / Math.min(img.naturalWidth, img.naturalHeight)
      setZoom(cover)
      setOffset({ x: 0, y: 0 })
      setSrcLoaded(true)
    }
    img.src = imageSrc
  }, [imageSrc])

  // ── load frame image ─────────────────────────────────────────────────────

  useEffect(() => {
    if (!frames.length) return
    setFrameLoaded(false)
    const img = new Image()
    img.onload = () => { frameImgRef.current = img; setFrameLoaded(true) }
    img.src = frames[frameIdx].url
  }, [frames, frameIdx])

  // ── render canvas ────────────────────────────────────────────────────────

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const cx = CANVAS_SIZE / 2
    const cy = CANVAS_SIZE / 2

    ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)

    if (srcImgRef.current) {
      ctx.save()
      ctx.beginPath()
      ctx.arc(cx, cy, CLIP_RADIUS, 0, Math.PI * 2)
      ctx.clip()
      const img = srcImgRef.current
      const w = img.naturalWidth * zoom
      const h = img.naturalHeight * zoom
      ctx.drawImage(img, cx - w / 2 + offset.x, cy - h / 2 + offset.y, w, h)
      ctx.restore()
    } else {
      ctx.save()
      ctx.beginPath()
      ctx.arc(cx, cy, CLIP_RADIUS, 0, Math.PI * 2)
      ctx.fillStyle = '#1a1a2e'
      ctx.fill()
      ctx.restore()
    }

    if (frameImgRef.current) {
      ctx.drawImage(frameImgRef.current, 0, 0, CANVAS_SIZE, CANVAS_SIZE)
    }
  }, [offset.x, offset.y, zoom, srcLoaded, frameLoaded])

  // ── mouse ────────────────────────────────────────────────────────────────

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true
    setIsDragging(true)
    dragOrigin.current = { mx: e.clientX, my: e.clientY, ox: offset.x, oy: offset.y }
  }, [offset.x, offset.y])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current || !dragOrigin.current) return
    const scale = CANVAS_SIZE / DISPLAY_SIZE
    const dx = (e.clientX - dragOrigin.current.mx) * scale
    const dy = (e.clientY - dragOrigin.current.my) * scale
    setOffset({ x: dragOrigin.current.ox + dx, y: dragOrigin.current.oy + dy })
  }, [])

  const onMouseUp = useCallback(() => {
    dragging.current = false
    setIsDragging(false)
    dragOrigin.current = null
  }, [])

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    setZoom((z) => {
      const next = Math.max(0.05, Math.min(10, z * (1 - e.deltaY * 0.001)))
      flashZoom()
      return next
    })
  }, [flashZoom])

  // ── touch ────────────────────────────────────────────────────────────────

  const lastTouch = useRef<{ x: number; y: number } | null>(null)

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      dragging.current = true
      setIsDragging(true)
      const t = e.touches[0]
      lastTouch.current = { x: t.clientX, y: t.clientY }
      dragOrigin.current = { mx: t.clientX, my: t.clientY, ox: offset.x, oy: offset.y }
    }
  }, [offset.x, offset.y])

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    e.preventDefault()
    if (e.touches.length === 1 && dragging.current && dragOrigin.current) {
      const t = e.touches[0]
      const scale = CANVAS_SIZE / DISPLAY_SIZE
      const dx = (t.clientX - dragOrigin.current.mx) * scale
      const dy = (t.clientY - dragOrigin.current.my) * scale
      setOffset({ x: dragOrigin.current.ox + dx, y: dragOrigin.current.oy + dy })
    }
  }, [])

  const onTouchEnd = useCallback(() => {
    dragging.current = false
    setIsDragging(false)
    lastTouch.current = null
    dragOrigin.current = null
  }, [])

  // ── keyboard ─────────────────────────────────────────────────────────────

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      const STEP = 5
      switch (e.key) {
        case 'ArrowLeft':  e.preventDefault(); setOffset((o) => ({ ...o, x: o.x - STEP })); break
        case 'ArrowRight': e.preventDefault(); setOffset((o) => ({ ...o, x: o.x + STEP })); break
        case 'ArrowUp':    e.preventDefault(); setOffset((o) => ({ ...o, y: o.y - STEP })); break
        case 'ArrowDown':  e.preventDefault(); setOffset((o) => ({ ...o, y: o.y + STEP })); break
        case '+': case '=': setZoom((z) => { flashZoom(); return Math.min(10, z * 1.1) }); break
        case '-': case '_': setZoom((z) => { flashZoom(); return Math.max(0.05, z * 0.9) }); break
        case '0': setZoom(1); flashZoom(); break
        case 'r': case 'R': resetView(); break
        case '[': setFrameIdx((i) => (i - 1 + frames.length) % Math.max(1, frames.length)); break
        case ']': setFrameIdx((i) => (i + 1) % Math.max(1, frames.length)); break
        case 'Escape': router.push(`/gm/view/${item.uuid || item.id}`); break
        case 's': case 'S': saveAndReturnRef.current(); break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frames.length, router, item.id, flashZoom])

  // ── set default frame ────────────────────────────────────────────────────

  async function setAsDefault() {
    const name = frames[frameIdx]?.name
    if (!name) return
    try {
      const r = await fetch('/api/gm/token/frames', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ defaultFrame: name }),
      })
      if (!r.ok) throw new Error(await r.text())
      setDefaultFrame(name)
      showMsg(`Default → ${name}`, true)
    } catch (err) {
      showMsg(String(err), false)
    }
  }

  // ── save token ───────────────────────────────────────────────────────────

  const saveToken = useCallback(async (): Promise<boolean> => {
    const canvas = canvasRef.current
    if (!canvas) return false
    setSaving(true)
    try {
      const imageData = canvas.toDataURL('image/png')
      const r = await fetch('/api/gm/token/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          imageData,
          filename: item.filename,
          sourcePath: item.source[0] ?? '',
          existingTokenPath: item.tokenPath,
        }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json() as { ok: boolean; tokenUrl: string }
      setSavedTokenUrl(data.tokenUrl + '&t=' + Date.now())
      showMsg('Saved', true)
      return true
    } catch (err) {
      showMsg(String(err), false)
      return false
    } finally {
      setSaving(false)
    }
  }, [item.filename, item.tokenPath, showMsg])

  const saveAndReturn = useCallback(async () => {
    const ok = await saveToken()
    if (ok) router.push(`/gm/view/${item.uuid || item.id}`)
  }, [saveToken, router, item.id])

  useEffect(() => { saveTokenRef.current = saveToken }, [saveToken])
  useEffect(() => { saveAndReturnRef.current = saveAndReturn }, [saveAndReturn])

  // ── auto-save ────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!srcLoaded || !frames.length) return
    const id = setTimeout(() => { initDone.current = true }, 200)
    return () => clearTimeout(id)
  }, [srcLoaded, frames.length])

  useEffect(() => {
    if (!initDone.current) return
    const id = setTimeout(() => saveTokenRef.current(), 1500)
    return () => clearTimeout(id)
  }, [offset.x, offset.y, zoom, frameIdx])

  // ── reset ────────────────────────────────────────────────────────────────

  function resetView() {
    setOffset({ x: 0, y: 0 })
    if (srcImgRef.current) {
      const img = srcImgRef.current
      const z = (CLIP_RADIUS * 2) / Math.min(img.naturalWidth, img.naturalHeight)
      setZoom(z)
      flashZoom()
    } else {
      setZoom(1)
    }
  }

  // ── derived ──────────────────────────────────────────────────────────────

  const currentFrame = frames[frameIdx]
  const isDefault = currentFrame?.name === defaultFrame
  const displayTokenUrl = savedTokenUrl ?? tokenSrc

  // ── render ───────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-zinc-950 text-white">

      {/* ── Top bar ── */}
      <header className="shrink-0 h-10 bg-surface-1 border-b border-surface-3 px-4 flex items-center gap-2 z-20">
        <Link
          href={`/gm/view/${item.uuid || item.id}`}
          className="text-zinc-500 hover:text-zinc-300 transition-colors text-xs flex items-center gap-1 shrink-0"
        >
          ← back
        </Link>
        <span className="text-surface-4 text-xs">/</span>
        <span className="font-mono text-xs text-zinc-300 truncate max-w-[220px]">{item.id}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded border border-surface-3 bg-surface-3 text-zinc-500 uppercase tracking-widest shrink-0">
          Token Editor
        </span>

        <div className="flex-1" />

        <Tip label="Save & return to item" shortcut="S" side="bottom">
          <button
            onClick={saveAndReturn}
            disabled={saving || !srcLoaded}
            className={`inline-flex items-center gap-1.5 h-7 px-3 rounded text-xs font-medium border transition-all ${
              srcLoaded
                ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/20'
                : 'opacity-30 cursor-not-allowed border-surface-3 bg-surface-2 text-zinc-500'
            }`}
          >
            {saving ? (
              <span className="inline-block w-3 h-3 border border-emerald-400/40 border-t-emerald-400 rounded-full animate-spin" />
            ) : (
              <svg className="w-3 h-3" fill="none" viewBox="0 0 16 16" stroke="currentColor" strokeWidth={1.8}>
                <path d="M13 11V3H3v10h7l3-2z" strokeLinejoin="round" />
                <path d="M5 3v3h5V3" strokeLinejoin="round" />
                <path d="M5 9h4" strokeLinecap="round" />
              </svg>
            )}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </Tip>
      </header>

      {/* ── Main ── */}
      <main className="flex-1 relative flex flex-col items-center justify-center gap-3 overflow-hidden select-none">

        {/* ── Control strip ── */}
        <div className="flex items-center gap-1 bg-zinc-900/70 border border-zinc-800/80 backdrop-blur-sm rounded-xl px-2.5 py-1.5 shadow-xl">

          {/* Zoom controls */}
          <IconBtn
            label="Zoom out"
            shortcut="−"
            onClick={() => { setZoom((z) => { flashZoom(); return Math.max(0.05, z * 0.87) }) }}
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 14 14" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
              <circle cx="6" cy="6" r="4.5" />
              <line x1="9.5" y1="9.5" x2="13" y2="13" />
              <line x1="3.5" y1="6" x2="8.5" y2="6" />
            </svg>
          </IconBtn>

          {/* Zoom slider */}
          <Tip label="Drag to zoom" side="bottom">
            <input
              type="range"
              min={0.05} max={10} step={0.005}
              value={zoom}
              onChange={(e) => { setZoom(Number(e.target.value)); flashZoom() }}
              className="w-24 h-1 accent-zinc-400 cursor-pointer"
            />
          </Tip>

          <IconBtn
            label="Zoom in"
            shortcut="+"
            onClick={() => { setZoom((z) => { flashZoom(); return Math.min(10, z * 1.15) }) }}
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 14 14" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
              <circle cx="6" cy="6" r="4.5" />
              <line x1="9.5" y1="9.5" x2="13" y2="13" />
              <line x1="6" y1="3.5" x2="6" y2="8.5" />
              <line x1="3.5" y1="6" x2="8.5" y2="6" />
            </svg>
          </IconBtn>

          <Div />

          <IconBtn label="Reset view" shortcut="R" onClick={resetView}>
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 16 16" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M2.5 8A5.5 5.5 0 1 0 4 4.2L2 2" />
              <path d="M2 2v3h3" />
            </svg>
          </IconBtn>

          <Div />

          {/* Frame nav */}
          <IconBtn
            label="Previous frame"
            shortcut="["
            disabled={frames.length < 2}
            onClick={() => setFrameIdx((i) => (i - 1 + frames.length) % frames.length)}
            size="sm"
          >
            <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 10 10" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 2L3 5l3 3" />
            </svg>
          </IconBtn>

          <Tip label={currentFrame?.name ?? 'Loading…'} side="bottom">
            <div className="w-7 h-7 rounded-full overflow-hidden border border-zinc-700/60 bg-zinc-800 flex-shrink-0 cursor-default">
              {currentFrame && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={currentFrame.url} alt="" className="w-full h-full object-contain" />
              )}
            </div>
          </Tip>

          <IconBtn
            label="Next frame"
            shortcut="]"
            disabled={frames.length < 2}
            onClick={() => setFrameIdx((i) => (i + 1) % frames.length)}
            size="sm"
          >
            <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 10 10" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 2l3 3-3 3" />
            </svg>
          </IconBtn>

          <Div />

          <IconBtn
            label={isDefault ? 'Default frame' : 'Set as default frame'}
            variant="star"
            active={isDefault}
            disabled={!currentFrame}
            onClick={setAsDefault}
            side="bottom"
          >
            {isDefault ? '★' : '☆'}
          </IconBtn>

        </div>

        {/* ── Canvas ── */}
        <div className="relative" style={{ width: DISPLAY_SIZE, height: DISPLAY_SIZE }}>
          <canvas
            ref={canvasRef}
            width={CANVAS_SIZE}
            height={CANVAS_SIZE}
            className="rounded-full shadow-2xl"
            style={{
              width: DISPLAY_SIZE,
              height: DISPLAY_SIZE,
              touchAction: 'none',
              cursor: isDragging ? 'grabbing' : 'grab',
            }}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
            onWheel={onWheel}
            onTouchStart={onTouchStart}
            onTouchMove={onTouchMove}
            onTouchEnd={onTouchEnd}
          />

          {/* Zoom overlay */}
          <div
            className={`absolute inset-0 flex items-center justify-center pointer-events-none transition-opacity duration-300 ${zoomVisible ? 'opacity-100' : 'opacity-0'}`}
          >
            <span className="bg-zinc-900/85 border border-zinc-700/60 backdrop-blur-sm text-white text-sm font-mono px-3 py-1.5 rounded-full shadow-lg">
              {zoom.toFixed(3)}×
            </span>
          </div>

          {/* Drag hint - shows when idle and image loaded */}
          {srcLoaded && !isDragging && (
            <div className="absolute bottom-4 inset-x-0 flex justify-center pointer-events-none">
              <span className="text-[10px] text-zinc-600">drag · scroll · arrow keys</span>
            </div>
          )}

          {/* No image placeholder */}
          {!imageSrc && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <span className="text-zinc-600 text-sm">No image</span>
            </div>
          )}
        </div>

        {/* ── Frame strip ── */}
        {frames.length > 1 && (
          <div className="flex items-center gap-1.5 px-3 py-2 bg-zinc-900/60 border border-zinc-800/70 backdrop-blur-sm rounded-xl max-w-[480px] overflow-x-auto">
            {frames.map((f, i) => (
              <Tip key={f.name} label={f.name} side="bottom">
                <button
                  onClick={() => setFrameIdx(i)}
                  className={`relative w-8 h-8 rounded-full overflow-hidden flex-shrink-0 border-2 transition-all ${
                    i === frameIdx
                      ? 'border-zinc-400 scale-110 shadow-lg'
                      : 'border-zinc-700/60 opacity-50 hover:opacity-80 hover:border-zinc-600'
                  }`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={f.url} alt={f.name} className="w-full h-full object-contain" />
                  {f.name === defaultFrame && (
                    <span className="absolute bottom-0 right-0 w-2 h-2 bg-amber-400 rounded-full border border-zinc-900" />
                  )}
                </button>
              </Tip>
            ))}
          </div>
        )}

      </main>

      {/* ── Token preview (fixed bottom-right) ── */}
      {displayTokenUrl && (
        <div
          className="fixed bottom-4 right-4 z-30 flex flex-col items-center gap-1.5 cursor-pointer group/preview"
          onMouseEnter={() => setTokenHovered(true)}
          onMouseLeave={() => setTokenHovered(false)}
        >
          <div
            className={`transition-all duration-300 ease-out rounded-full overflow-hidden border-2 shadow-2xl ${
              tokenHovered
                ? 'border-zinc-400 shadow-zinc-900/80'
                : 'border-zinc-700/60'
            }`}
            style={{ width: tokenHovered ? 160 : 64, height: tokenHovered ? 160 : 64 }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={displayTokenUrl}
              alt="Token preview"
              className="w-full h-full object-contain"
            />
          </div>
          <span
            className={`text-[10px] font-mono transition-opacity ${tokenHovered ? 'opacity-60 text-zinc-400' : 'opacity-30 text-zinc-600'}`}
          >
            {tokenHovered ? (
              <a
                href={displayTokenUrl}
                target="_blank"
                rel="noreferrer"
                className="hover:text-zinc-300 hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                open full ↗
              </a>
            ) : 'token'}
          </span>
        </div>
      )}

      {/* ── File info (fixed bottom-left) ── */}
      <div className="fixed bottom-4 left-4 z-30 flex flex-col gap-0.5">
        {srcDims && (
          <span className="text-[10px] font-mono text-zinc-700">
            {srcDims.w}×{srcDims.h}px
          </span>
        )}
        <span className="text-[10px] text-zinc-700 capitalize">{item.type}</span>
      </div>

      {/* ── Toast ── */}
      {msg && (
        <div
          className={`fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-4 py-2 rounded-full border shadow-2xl backdrop-blur-sm text-sm font-medium transition-all ${
            msg.ok
              ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400'
              : 'bg-red-500/10 border-red-500/40 text-red-400'
          }`}
        >
          {msg.ok ? (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 14 14" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <polyline points="2,7 6,11 12,3" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 14 14" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
              <line x1="2" y1="2" x2="12" y2="12" />
              <line x1="12" y1="2" x2="2" y2="12" />
            </svg>
          )}
          {msg.text}
        </div>
      )}

    </div>
  )
}
