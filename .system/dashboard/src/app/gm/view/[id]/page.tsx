export const dynamic = 'force-dynamic'

import { notFound } from 'next/navigation'
import { readItemDetail } from '@/lib/vault'
import ItemDetailView from '@/components/gm/ItemDetailView'

export default async function ItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const item = readItemDetail(decodeURIComponent(id))

  if (!item) {
    notFound()
  }

  return <ItemDetailView item={item} />
}
