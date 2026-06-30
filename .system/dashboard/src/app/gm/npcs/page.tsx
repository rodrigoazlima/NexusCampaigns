export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems, parseWantSecret } from '@/lib/vault'
import NpcCollection, { type NpcItem } from '@/components/gm/NpcCollection'

const NPC_TYPES = new Set(['npc', 'character'])

export default async function NpcsPage() {
  const drafts = readReviewItems().map((i) => ({ ...i, origin: 'draft' as const }))
  const canon = readLibraryItems().map((i) => ({ ...i, origin: 'canon' as const }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, NpcItem>()
  for (const e of [...drafts, ...canon]) {
    if (!NPC_TYPES.has(e.type)) continue
    const { want, hasSecret } = parseWantSecret(e.filepath)
    byId.set(e.id, { ...e, want, hasSecret })
  }

  const items = [...byId.values()]
  return <NpcCollection items={items} />
}
