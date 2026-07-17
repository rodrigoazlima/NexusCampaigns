'use client'

import { useState } from 'react'
import { defaultImageUrl, imageUrl } from '@/lib/image'

interface VaultImageProps extends Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src' | 'onError'> {
  path: string | null | undefined
  type?: string | null
  thumb?: boolean
  cacheBust?: string | number | null
}

export default function VaultImage({ path, type, thumb, cacheBust, alt = '', ...rest }: VaultImageProps) {
  const [failed, setFailed] = useState(false)
  const [prevPath, setPrevPath] = useState(path)
  if (path !== prevPath) {
    setPrevPath(path)
    setFailed(false)
  }

  const src = failed ? defaultImageUrl(type) : (imageUrl(path, { thumb, cacheBust }) ?? defaultImageUrl(type))

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} onError={() => setFailed(true)} {...rest} />
  )
}
