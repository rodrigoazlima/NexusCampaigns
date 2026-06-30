import { NextRequest, NextResponse } from 'next/server'
import { writeCampaign } from '@/lib/vault'

export const dynamic = 'force-dynamic'

// Create/update the active campaign frame (03-Campaigns/, type: campaign).
export async function POST(req: NextRequest) {
  try {
    const b = (await req.json()) as Record<string, string>
    const frame = writeCampaign({
      id: b.id,
      pitch: (b.pitch ?? '').trim(),
      tone_primary: b.tone_primary ?? '',
      tone_secondary: b.tone_secondary ?? '',
      scale: b.scale ?? '',
      central_tension: (b.central_tension ?? '').trim(),
      player_buyin: (b.player_buyin ?? '').trim(),
    })
    return NextResponse.json({ ok: true, frame })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
