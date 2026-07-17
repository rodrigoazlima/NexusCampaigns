export const dynamic = 'force-dynamic'

import { notFound } from 'next/navigation'
import { readItemDetail } from '@/lib/vault'
import { defaultImageUrl, imageUrl } from '@/lib/image'
import TokenEditorCanvas from '@/components/gm/TokenEditorCanvas'

export default async function TokenEditorPage({
  params,
}: {
  params: Promise<{ uuid: string }>
}) {
  const { uuid } = await params
  const item = readItemDetail(decodeURIComponent(uuid))

  if (!item) notFound()

  const imageSrc = imageUrl(item.source[0]) ?? defaultImageUrl(item.type)
  const tokenSrc = imageUrl(item.tokenPath)

  return <TokenEditorCanvas item={item} imageSrc={imageSrc} tokenSrc={tokenSrc} />
}
