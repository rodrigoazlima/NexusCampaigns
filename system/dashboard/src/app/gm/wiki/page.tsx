export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems } from '@/lib/vault'
import { pillarOf } from '@/lib/pillars'
import WikiBrowser, { type WikiItem } from '@/components/gm/WikiBrowser'

export default async function WikiPage() {
  const drafts = readReviewItems().map((i) => ({ ...i, origin: 'draft' as const }))
  const canon = readLibraryItems().map((i) => ({ ...i, origin: 'canon' as const }))

  // Canon wins on id collision (an approved draft also lives in Processing).
  const byId = new Map<string, WikiItem>()
  for (const e of [...drafts, ...canon]) {
    byId.set(e.id, { ...e, pillar: pillarOf(e.type) })
  }

  return <WikiBrowser items={[...byId.values()]} />
}
