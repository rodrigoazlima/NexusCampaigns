export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems, parsePlace } from '@/lib/vault'
import PlaceCollection, { type PlaceItem } from '@/components/gm/PlaceCollection'

const PLACE_TYPES = new Set(['location', 'city', 'village', 'dungeon'])

export default async function PlacesPage() {
  const drafts = readReviewItems().map((i) => ({ ...i, origin: 'draft' as const }))
  const canon = readLibraryItems().map((i) => ({ ...i, origin: 'canon' as const }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, PlaceItem>()
  for (const e of [...drafts, ...canon]) {
    if (!PLACE_TYPES.has(e.type)) continue
    byId.set(e.id, { ...e, ...parsePlace(e.filepath) })
  }

  return <PlaceCollection items={[...byId.values()]} />
}
