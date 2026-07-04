export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems, parseBestiary } from '@/lib/vault'
import BestiaryCollection, { type BestiaryItem } from '@/components/gm/BestiaryCollection'

const BESTIARY_TYPES = new Set(['creature', 'monster', 'encounter'])

export default async function BestiaryPage() {
  const drafts = readReviewItems().map((i) => ({ ...i, origin: 'draft' as const }))
  const canon = readLibraryItems().map((i) => ({ ...i, origin: 'canon' as const }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, BestiaryItem>()
  for (const e of [...drafts, ...canon]) {
    if (!BESTIARY_TYPES.has(e.type)) continue
    byId.set(e.id, { ...e, ...parseBestiary(e.filepath, e.tags) })
  }

  return <BestiaryCollection items={[...byId.values()]} />
}
