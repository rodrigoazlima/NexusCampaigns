'use client'

import VaultImage from '@/components/shared/VaultImage'

const IMAGE_EXT = /\.(jpg|jpeg|png|webp|gif|bmp)$/i

export default function QueueThumb({ path }: { path: string }) {
  if (!IMAGE_EXT.test(path)) return null

  return (
    <VaultImage path={path} thumb loading="lazy" decoding="async" className="w-8 h-8 rounded object-cover bg-surface-3" alt="" />
  )
}
