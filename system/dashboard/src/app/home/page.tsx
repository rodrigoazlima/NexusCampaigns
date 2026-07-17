export const dynamic = 'force-dynamic'

import Link from 'next/link'
import { readReviewItems, readLibraryItems } from '@/lib/vault'
import { PILLARS } from '@/lib/pillars'
import type { ReviewItem } from '@/lib/types'
import CarouselRow from '@/components/home/CarouselRow'

type Entry = ReviewItem & { origin: 'draft' | 'canon' }

export default function HomePage() {
  const drafts = readReviewItems().map((i): Entry => ({ ...i, origin: 'draft' }))
  const canon = readLibraryItems().map((i): Entry => ({ ...i, origin: 'canon' }))

  const byId = new Map<string, Entry>()
  for (const e of [...drafts, ...canon]) byId.set(e.id, e)
  const all = [...byId.values()]

  const rows = PILLARS.map((p) => ({
    pillar: p,
    items: all
      .filter((e) => p.types.includes(e.type))
      .sort((a, b) => (b.updated ?? '').localeCompare(a.updated ?? '')),
  })).filter((r) => r.items.length > 0)

  return (
    <div className="p-4 md:p-6 space-y-8">
      {rows.length === 0 ? (
        <div className="panel p-12 text-center text-zinc-500 text-sm">
          Nothing to show yet - drop sources in the <Link href="/gm/inbox" className="text-primary hover:underline">Inbox</Link>
        </div>
      ) : (
        rows.map(({ pillar, items }) => <CarouselRow key={pillar.key} pillarKey={pillar.key} items={items} />)
      )}
    </div>
  )
}
