'use client'

import { useEffect } from 'react'
import { X } from 'lucide-react'

interface ImageModalProps {
  src: string
  alt: string
  open: boolean
  onClose: () => void
}

export default function ImageModal({ src, alt, open, onClose }: ImageModalProps) {
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/80 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Image */}
      <div className="relative z-10 max-w-4xl w-full mx-4">
        <button
          onClick={onClose}
          className="absolute -top-10 right-0 p-2 text-zinc-300 hover:text-white transition-colors"
          aria-label="Close"
        >
          <X size={20} />
        </button>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={alt}
          className="max-h-[90vh] w-full object-contain rounded-lg"
        />
      </div>
    </div>
  )
}
