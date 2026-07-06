import { readInboxImages } from '@/lib/vault'
import { NextRequest, NextResponse } from 'next/server'
import type { InboxPage } from '@/lib/types'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const offset = Math.max(0, Number(searchParams.get('offset')) || 0)
  const limit = Math.min(200, Math.max(1, Number(searchParams.get('limit')) || 60))

  const all = readInboxImages()
  let stuck = 0
  let withToken = 0
  for (const item of all) {
    if (item.isStuck) stuck++
    if (item.hasToken) withToken++
  }

  const page: InboxPage = {
    total: all.length,
    stuck,
    withToken,
    items: all.slice(offset, offset + limit),
  }
  return NextResponse.json(page)
}
