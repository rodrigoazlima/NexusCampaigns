export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems, parseQuest } from '@/lib/vault'
import QuestCollection, { type QuestItem } from '@/components/gm/QuestCollection'

const QUEST_TYPES = new Set(['quest', 'event', 'timeline'])

export default async function QuestsPage() {
  const drafts = readReviewItems().map((i) => ({ ...i, origin: 'draft' as const }))
  const canon = readLibraryItems().map((i) => ({ ...i, origin: 'canon' as const }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, QuestItem>()
  for (const e of [...drafts, ...canon]) {
    if (!QUEST_TYPES.has(e.type)) continue
    byId.set(e.id, { ...e, ...parseQuest(e.filepath, e.tags) })
  }

  return <QuestCollection items={[...byId.values()]} />
}
