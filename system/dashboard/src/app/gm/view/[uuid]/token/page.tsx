export const dynamic = 'force-dynamic'

import { notFound } from 'next/navigation'
import { readItemDetail } from '@/lib/vault'
import TokenEditorCanvas from '@/components/gm/TokenEditorCanvas'

export default async function TokenEditorPage({
  params,
}: {
  params: Promise<{ uuid: string }>
}) {
  const { uuid } = await params
  const item = readItemDetail(decodeURIComponent(uuid))

  if (!item) notFound()

  const imageSrc = item.source[0]
    ? `/api/image?path=${encodeURIComponent(item.source[0])}`
    : null

  const tokenSrc = item.tokenPath
    ? `/api/image?path=${encodeURIComponent(item.tokenPath)}`
    : null

  return <TokenEditorCanvas item={item} imageSrc={imageSrc} tokenSrc={tokenSrc} />
}
