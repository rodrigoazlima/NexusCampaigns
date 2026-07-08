'use client'

import { useState } from 'react'
import { ImageOff } from 'lucide-react'

const IMAGE_EXT = /\.(jpg|jpeg|png|webp|gif|bmp)$/i

export default function QueueThumb({ path }: { path: string }) {
  const [missing, setMissing] = useState(false)

  if (!IMAGE_EXT.test(path)) return null

  if (missing) {
    return (
      <div
        title="Source file missing from disk"
        className="w-8 h-8 rounded bg-surface-3 flex items-center justify-center text-zinc-600"
      >
        <ImageOff size={14} />
      </div>
    )
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`/api/image?path=${encodeURIComponent(path)}&thumb=1`}
      alt=""
      loading="lazy"
      decoding="async"
      className="w-8 h-8 rounded object-cover bg-surface-3"
      onError={() => setMissing(true)}
    />
  )
}
