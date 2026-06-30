export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems, parseFaction } from '@/lib/vault'
import FactionCollection, { type FactionItem } from '@/components/gm/FactionCollection'

const FACTION_TYPES = new Set(['faction', 'organization', 'religion'])

export default async function FactionsPage() {
  const drafts = readReviewItems().map((i) => ({ ...i, origin: 'draft' as const }))
  const canon = readLibraryItems().map((i) => ({ ...i, origin: 'canon' as const }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, FactionItem>()
  for (const e of [...drafts, ...canon]) {
    if (!FACTION_TYPES.has(e.type)) continue
    byId.set(e.id, { ...e, ...parseFaction(e.filepath) })
  }

  return <FactionCollection items={[...byId.values()]} />
}
