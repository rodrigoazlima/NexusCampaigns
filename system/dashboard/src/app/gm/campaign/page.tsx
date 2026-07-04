export const dynamic = 'force-dynamic'

import { readReviewItems, readLibraryItems, readActiveCampaign } from '@/lib/vault'
import { buildCampaignData, type Entry } from '@/lib/campaign'
import CampaignView from '@/components/gm/CampaignView'

export default async function CampaignPage() {
  const drafts = readReviewItems().map((i): Entry => ({ ...i, origin: 'draft' }))
  const canon = readLibraryItems().map((i): Entry => ({ ...i, origin: 'canon' }))
  const data = buildCampaignData(drafts, canon)
  const frame = readActiveCampaign()
  return <CampaignView data={data} frame={frame} />
}
