'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { uploadImage, isImageFile } from '@/lib/upload-image'

type Phase = 'idle' | 'dragging' | 'uploading' | 'done'
interface DropState {
  phase: Phase
  count?: number
  uploaded?: number
  failed?: number
}

function hasDraggableFiles(dt: DataTransfer | null): boolean {
  return !!dt && Array.from(dt.items).some(i => i.kind === 'file')
}

export default function GlobalDropZone() {
  const [state, setState] = useState<DropState>({ phase: 'idle' })
  const counter = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const reset = useCallback(() => {
    counter.current = 0
    setState({ phase: 'idle' })
  }, [])

  useEffect(() => {
    function onEnter(e: DragEvent) {
      if (!hasDraggableFiles(e.dataTransfer)) return
      e.preventDefault()
      counter.current++
      if (counter.current === 1) setState({ phase: 'dragging' })
    }

    function onOver(e: DragEvent) {
      if (!hasDraggableFiles(e.dataTransfer)) return
      e.preventDefault()
      e.dataTransfer!.dropEffect = 'copy'
    }

    function onLeave() {
      counter.current = Math.max(0, counter.current - 1)
      if (counter.current === 0) reset()
    }

    async function onDrop(e: DragEvent) {
      e.preventDefault()
      counter.current = 0

      const files = Array.from(e.dataTransfer?.files ?? []).filter(isImageFile)
      if (files.length === 0) { reset(); return }

      setState({ phase: 'uploading', count: files.length })
      const results = await Promise.all(files.map(f => uploadImage({ file: f })))
      const uploaded = results.filter(r => r.ok).length
      const failed = results.length - uploaded

      if (timer.current) clearTimeout(timer.current)
      setState({ phase: 'done', uploaded, failed })
      timer.current = setTimeout(reset, 3000)
    }

    document.addEventListener('dragenter', onEnter)
    document.addEventListener('dragover', onOver)
    document.addEventListener('dragleave', onLeave)
    document.addEventListener('drop', onDrop)
    return () => {
      document.removeEventListener('dragenter', onEnter)
      document.removeEventListener('dragover', onOver)
      document.removeEventListener('dragleave', onLeave)
      document.removeEventListener('drop', onDrop)
      if (timer.current) clearTimeout(timer.current)
    }
  }, [reset])

  const { phase, count = 0, uploaded = 0, failed = 0 } = state
  if (phase === 'idle') return null

  const borderColor =
    phase === 'done' && failed === 0 ? 'border-success' :
    phase === 'done' && failed > 0   ? 'border-danger'  :
    'border-primary'

  return (
    <div className="fixed inset-0 z-[100] pointer-events-none flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className={`flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed ${borderColor} p-12 bg-surface-1 shadow-2xl`}>
        {phase === 'dragging' && (
          <>
            <Upload size={44} className="text-primary" />
            <p className="text-lg font-semibold text-zinc-100">Drop to upload to Inbox</p>
            <p className="text-sm text-zinc-500">Images → <span className="font-mono">00-Inbox/images/</span></p>
          </>
        )}
        {phase === 'uploading' && (
          <>
            <Loader2 size={44} className="text-primary animate-spin" />
            <p className="text-lg font-semibold text-zinc-100">
              Uploading {count} image{count !== 1 ? 's' : ''}…
            </p>
          </>
        )}
        {phase === 'done' && (
          <>
            {failed === 0
              ? <CheckCircle size={44} className="text-success" />
              : <XCircle size={44} className="text-danger" />
            }
            <p className="text-lg font-semibold text-zinc-100">
              {uploaded} uploaded{failed > 0 ? `, ${failed} failed` : ''}
            </p>
          </>
        )}
      </div>
    </div>
  )
}
