export const dynamic = 'force-dynamic'

import { notFound } from 'next/navigation'
import { readItemDetail } from '@/lib/vault'
import ItemDetailView from '@/components/gm/ItemDetailView'

export default async function ItemDetailPage({
  params,
}: {
  params: Promise<{ uuid: string }>
}) {
  const { uuid } = await params
  const item = readItemDetail(decodeURIComponent(uuid))

  if (!item) {
    notFound()
  }

  return <ItemDetailView item={item} />
}
