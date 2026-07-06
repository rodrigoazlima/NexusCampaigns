'use client'

const IMAGE_EXT = /\.(jpg|jpeg|png|webp|gif|bmp)$/i

export default function QueueThumb({ path }: { path: string }) {
  if (!IMAGE_EXT.test(path)) return null
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`/api/image?path=${encodeURIComponent(path)}&thumb=1`}
      alt=""
      loading="lazy"
      decoding="async"
      className="w-8 h-8 rounded object-cover bg-surface-3"
      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
    />
  )
}
