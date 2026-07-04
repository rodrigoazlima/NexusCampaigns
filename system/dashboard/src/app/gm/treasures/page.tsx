export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems, parseTreasure } from '@/lib/vault'
import TreasuresCollection, { type TreasureItem } from '@/components/gm/TreasuresCollection'

const TREASURE_TYPES = new Set(['item', 'artifact', 'lore'])

export default async function TreasuresPage() {
  const drafts = readReviewItems().map((i) => ({ ...i, origin: 'draft' as const }))
  const canon = readLibraryItems().map((i) => ({ ...i, origin: 'canon' as const }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, TreasureItem>()
  for (const e of [...drafts, ...canon]) {
    if (!TREASURE_TYPES.has(e.type)) continue
    byId.set(e.id, { ...e, ...parseTreasure(e.filepath, e.tags) })
  }

  return <TreasuresCollection items={[...byId.values()]} />
}
