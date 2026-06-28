'use client'

import { useRef, useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import type { ItemDetail } from '@/lib/types'

interface Frame { name: string; url: string }

interface Props {
  item: ItemDetail
  imageSrc: string | null
  tokenSrc: string | null
}

const CANVAS_SIZE = 512
const CLIP_RADIUS = 234

export default function TokenEditorCanvas({ item, imageSrc, tokenSrc }: Props) {
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

  const dragging = useRef(false)
  const dragOrigin = useRef<{ mx: number; my: number; ox: number; oy: number } | null>(null)

  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [savedTokenUrl, setSavedTokenUrl] = useState<string | null>(null)

  // Load frames
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

  // Load source image
  useEffect(() => {
    if (!imageSrc) return
    setSrcLoaded(false)
    const img = new Image()
    img.onload = () => {
      srcImgRef.current = img
      const cover = (CLIP_RADIUS * 2) / Math.min(img.naturalWidth, img.naturalHeight)
      setZoom(cover)
      setOffset({ x: 0, y: 0 })
      setSrcLoaded(true)
    }
    img.src = imageSrc
  }, [imageSrc])

  // Load frame image
  useEffect(() => {
    if (!frames.length) return
    setFrameLoaded(false)
    const img = new Image()
    img.onload = () => { frameImgRef.current = img; setFrameLoaded(true) }
    img.src = frames[frameIdx].url
  }, [frames, frameIdx])

  // Render canvas
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

  // Mouse handlers
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true
    dragOrigin.current = { mx: e.clientX, my: e.clientY, ox: offset.x, oy: offset.y }
  }, [offset.x, offset.y])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current || !dragOrigin.current) return
    const scale = CANVAS_SIZE / 400
    const dx = (e.clientX - dragOrigin.current.mx) * scale
    const dy = (e.clientY - dragOrigin.current.my) * scale
    setOffset({ x: dragOrigin.current.ox + dx, y: dragOrigin.current.oy + dy })
  }, [])

  const onMouseUp = useCallback(() => {
    dragging.current = false
    dragOrigin.current = null
  }, [])

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    setZoom((z) => Math.max(0.05, Math.min(10, z * (1 - e.deltaY * 0.001))))
  }, [])

  // Touch handlers
  const lastTouch = useRef<{ x: number; y: number } | null>(null)

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      dragging.current = true
      const t = e.touches[0]
      lastTouch.current = { x: t.clientX, y: t.clientY }
      dragOrigin.current = { mx: t.clientX, my: t.clientY, ox: offset.x, oy: offset.y }
    }
  }, [offset.x, offset.y])

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    e.preventDefault()
    if (e.touches.length === 1 && dragging.current && dragOrigin.current) {
      const t = e.touches[0]
      const scale = CANVAS_SIZE / 400
      const dx = (t.clientX - dragOrigin.current.mx) * scale
      const dy = (t.clientY - dragOrigin.current.my) * scale
      setOffset({ x: dragOrigin.current.ox + dx, y: dragOrigin.current.oy + dy })
    }
  }, [])

  const onTouchEnd = useCallback(() => {
    dragging.current = false
    lastTouch.current = null
    dragOrigin.current = null
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      const STEP = 5
      switch (e.key) {
        case 'ArrowLeft':  e.preventDefault(); setOffset((o) => ({ ...o, x: o.x - STEP })); break
        case 'ArrowRight': e.preventDefault(); setOffset((o) => ({ ...o, x: o.x + STEP })); break
        case 'ArrowUp':    e.preventDefault(); setOffset((o) => ({ ...o, y: o.y - STEP })); break
        case 'ArrowDown':  e.preventDefault(); setOffset((o) => ({ ...o, y: o.y + STEP })); break
        case '+': case '=': setZoom((z) => Math.min(10, z * 1.1)); break
        case '-': case '_': setZoom((z) => Math.max(0.05, z * 0.9)); break
        case '0': setZoom(1); break
        case 'r': case 'R':
          setOffset({ x: 0, y: 0 })
          if (srcImgRef.current) {
            const img = srcImgRef.current
            setZoom((CLIP_RADIUS * 2) / Math.min(img.naturalWidth, img.naturalHeight))
          } else {
            setZoom(1)
          }
          break
        case '[': setFrameIdx((i) => (i - 1 + frames.length) % Math.max(1, frames.length)); break
        case ']': setFrameIdx((i) => (i + 1) % Math.max(1, frames.length)); break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [frames.length])

  // Set default frame
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
      setMsg({ text: `Default set to ${name}`, ok: true })
    } catch (err) {
      setMsg({ text: String(err), ok: false })
    }
  }

  // Save token
  async function saveToken() {
    const canvas = canvasRef.current
    if (!canvas) return
    setSaving(true); setMsg(null)
    try {
      const imageData = canvas.toDataURL('image/png')
      const r = await fetch('/api/gm/token/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ imageData, filename: item.filename }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json() as { ok: boolean; tokenUrl: string }
      setSavedTokenUrl(data.tokenUrl + '&t=' + Date.now())
      setMsg({ text: 'Token saved', ok: true })
    } catch (err) {
      setMsg({ text: String(err), ok: false })
    } finally {
      setSaving(false)
    }
  }

  function resetView() {
    setOffset({ x: 0, y: 0 })
    if (srcImgRef.current) {
      const img = srcImgRef.current
      setZoom((CLIP_RADIUS * 2) / Math.min(img.naturalWidth, img.naturalHeight))
    } else {
      setZoom(1)
    }
  }

  const currentFrame = frames[frameIdx]
  const displayTokenUrl = savedTokenUrl ?? tokenSrc

  return (
    <div className="flex flex-col h-screen overflow-hidden">

      {/* Top bar */}
      <div className="shrink-0 bg-surface-1 border-b border-surface-3 px-5 py-2.5 flex items-center gap-3 z-10">
        <Link
          href={`/gm/view/${item.id}`}
          className="text-zinc-400 hover:text-white transition-colors text-sm flex items-center gap-1"
        >
          ← Item View
        </Link>
        <span className="text-surface-3">|</span>
        <span className="text-white font-medium font-mono text-sm truncate max-w-xs">{item.id}</span>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border border-surface-3 bg-surface-3 text-zinc-400 normal-case tracking-normal">
          Token Editor
        </span>

        <div className="flex-1" />

        {msg && (
          <span className={`text-sm shrink-0 ${msg.ok ? 'text-success' : 'text-danger'}`}>
            {msg.ok ? '✓' : '✗'} {msg.text}
          </span>
        )}

        <button
          onClick={saveToken}
          disabled={saving || !srcLoaded}
          className={`inline-flex items-center gap-2 px-3 py-1.5 rounded text-sm font-medium border transition-colors ${
            srcLoaded
              ? 'bg-success/15 border-success/40 text-success hover:bg-success/25'
              : 'opacity-40 cursor-not-allowed border-surface-3 bg-surface-2 text-zinc-500'
          }`}
        >
          {saving ? '…' : '💾 Save Token'}
        </button>
      </div>

      {/* Main */}
      <div className="flex flex-1 overflow-hidden">

        {/* Canvas area */}
        <div className="flex-1 bg-zinc-950 flex items-center justify-center select-none">
          <div className="flex flex-col items-center gap-4">
            <canvas
              ref={canvasRef}
              width={CANVAS_SIZE}
              height={CANVAS_SIZE}
              className={`rounded-full shadow-2xl ring-1 ring-surface-3 ${dragging.current ? 'cursor-grabbing' : 'cursor-grab'}`}
              style={{ width: 400, height: 400, touchAction: 'none' }}
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={onMouseUp}
              onWheel={onWheel}
              onTouchStart={onTouchStart}
              onTouchMove={onTouchMove}
              onTouchEnd={onTouchEnd}
            />
            <div className="text-xs text-zinc-500 text-center space-y-0.5">
              <div>Drag to reposition · Scroll to zoom · Arrow keys to nudge</div>
              <div className="font-mono text-zinc-600">[ ] = prev/next frame · R = reset · +/- = zoom</div>
            </div>
          </div>
        </div>

        {/* Right panel */}
        <div className="w-72 shrink-0 border-l border-surface-3 bg-surface-1 overflow-y-auto">
          <div className="p-4 space-y-5">

            {/* Transform */}
            <section>
              <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-3">Transform</div>
              <div className="space-y-3">
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-zinc-500">Zoom</span>
                    <span className="font-mono text-white">{zoom.toFixed(3)}×</span>
                  </div>
                  <input
                    type="range" min={0.05} max={10} step={0.005}
                    value={zoom}
                    onChange={(e) => setZoom(Number(e.target.value))}
                    className="w-full accent-primary cursor-pointer"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-zinc-500 block">X offset</span>
                    <span className="font-mono text-white">{offset.x.toFixed(1)}px</span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block">Y offset</span>
                    <span className="font-mono text-white">{offset.y.toFixed(1)}px</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => setZoom((z) => Math.min(10, z * 1.15))}
                    className="inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded text-xs font-medium border border-surface-3 bg-surface-2 text-zinc-300 hover:bg-surface-3 hover:text-white transition-colors"
                  >
                    + Zoom in
                  </button>
                  <button
                    onClick={() => setZoom((z) => Math.max(0.05, z * 0.87))}
                    className="inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded text-xs font-medium border border-surface-3 bg-surface-2 text-zinc-300 hover:bg-surface-3 hover:text-white transition-colors"
                  >
                    − Zoom out
                  </button>
                </div>
                <button
                  onClick={resetView}
                  className="inline-flex items-center justify-center gap-2 w-full px-3 py-1.5 rounded text-xs font-medium border border-surface-3 bg-surface-2 text-zinc-300 hover:bg-surface-3 hover:text-white transition-colors"
                >
                  ↺ Reset
                </button>
              </div>
            </section>

            <div className="border-t border-surface-3" />

            {/* Frame selector */}
            <section>
              <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-3">
                Frame
                {frames.length > 0 && (
                  <span className="ml-1 font-normal normal-case tracking-normal text-zinc-500">
                    ({frameIdx + 1}/{frames.length})
                  </span>
                )}
              </div>

              {frames.length > 0 ? (
                <>
                  <div className="flex items-center gap-2 mb-3">
                    <button
                      onClick={() => setFrameIdx((i) => (i - 1 + frames.length) % frames.length)}
                      className="inline-flex items-center justify-center px-2.5 py-1 rounded text-xs font-medium border border-surface-3 bg-surface-2 text-zinc-300 hover:bg-surface-3 hover:text-white transition-colors shrink-0"
                      title="Previous frame ["
                    >
                      ‹
                    </button>
                    <div className="flex-1 text-center text-xs text-zinc-300 truncate font-mono" title={currentFrame?.name}>
                      {currentFrame?.name ?? '—'}
                    </div>
                    <button
                      onClick={() => setFrameIdx((i) => (i + 1) % frames.length)}
                      className="inline-flex items-center justify-center px-2.5 py-1 rounded text-xs font-medium border border-surface-3 bg-surface-2 text-zinc-300 hover:bg-surface-3 hover:text-white transition-colors shrink-0"
                      title="Next frame ]"
                    >
                      ›
                    </button>
                  </div>
                  <button
                    onClick={setAsDefault}
                    disabled={!currentFrame || currentFrame.name === defaultFrame}
                    className={`inline-flex items-center justify-center gap-2 w-full px-3 py-1.5 rounded text-xs font-medium border transition-colors mb-3 ${
                      currentFrame?.name === defaultFrame
                        ? 'opacity-40 cursor-not-allowed border-surface-3 bg-surface-2 text-zinc-500'
                        : 'border-primary/40 text-primary hover:bg-primary/10 bg-transparent'
                    }`}
                    title="Save as default frame for token automation"
                  >
                    {currentFrame?.name === defaultFrame ? '★ Default frame' : '☆ Set as default'}
                  </button>
                  {currentFrame && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={currentFrame.url}
                      alt={currentFrame.name}
                      className="w-28 h-28 object-contain mx-auto opacity-90 rounded-full"
                    />
                  )}
                </>
              ) : (
                <div className="text-xs text-zinc-500">Loading frames…</div>
              )}
            </section>

            <div className="border-t border-surface-3" />

            {/* File info */}
            <section>
              <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-3">File Info</div>
              <div className="space-y-1.5 text-xs">
                <InfoRow label="ID"><span className="font-mono text-zinc-300 break-all">{item.id}</span></InfoRow>
                <InfoRow label="Type"><span className="text-zinc-300">{item.type}</span></InfoRow>
                {item.source[0] && (
                  <InfoRow label="Source"><span className="text-zinc-400 break-all">{item.source[0]}</span></InfoRow>
                )}
                {item.created && (
                  <InfoRow label="Created"><span className="text-zinc-400">{item.created}</span></InfoRow>
                )}
                {srcImgRef.current && (
                  <InfoRow label="Dimensions">
                    <span className="font-mono text-zinc-300">
                      {srcImgRef.current.naturalWidth}×{srcImgRef.current.naturalHeight}
                    </span>
                  </InfoRow>
                )}
              </div>
            </section>

            <div className="border-t border-surface-3" />

            {/* Current token */}
            <section>
              <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-3">Current Token</div>
              {displayTokenUrl ? (
                <div className="flex flex-col items-center gap-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={displayTokenUrl}
                    alt="Current token"
                    className="w-28 h-28 object-contain rounded-full ring-1 ring-surface-3"
                  />
                  <a
                    href={displayTokenUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-primary hover:underline"
                  >
                    Open full size ↗
                  </a>
                </div>
              ) : (
                <div className="text-xs text-zinc-500">No token generated yet</div>
              )}
            </section>

            <div className="border-t border-surface-3" />

            {/* Shortcuts */}
            <section>
              <div className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-3">Shortcuts</div>
              <div className="space-y-1.5 text-xs">
                <ShortcutRow keys={['↑', '↓', '←', '→']} desc="Nudge 5px" />
                <ShortcutRow keys={['+', '-']} desc="Zoom ±10%" />
                <ShortcutRow keys={['0']} desc="Reset zoom to 1×" />
                <ShortcutRow keys={['R']} desc="Reset all" />
                <ShortcutRow keys={['[', ']']} desc="Prev/next frame" />
                <ShortcutRow keys={['Wheel']} desc="Zoom" />
                <ShortcutRow keys={['Drag']} desc="Reposition" />
              </div>
            </section>

          </div>
        </div>
      </div>
    </div>
  )
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-zinc-500 uppercase tracking-wide shrink-0 mt-0.5 text-[10px]">{label}</span>
      <div className="text-right min-w-0 max-w-[160px]">{children}</div>
    </div>
  )
}

function ShortcutRow({ keys, desc }: { keys: string[]; desc: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex gap-1 shrink-0">
        {keys.map((k) => (
          <kbd key={k} className="px-1.5 py-0.5 bg-surface-3 border border-surface-3 rounded font-mono text-white text-xs leading-tight">
            {k}
          </kbd>
        ))}
      </div>
      <span className="text-zinc-500 text-right">{desc}</span>
    </div>
  )
}
