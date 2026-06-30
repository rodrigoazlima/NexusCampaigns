import { NextRequest, NextResponse } from 'next/server'
import { readItemDetail } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ uuid: string }> }
) {
  try {
    const { uuid } = await params
    const item = readItemDetail(decodeURIComponent(uuid))
    if (!item) {
      return NextResponse.json({ error: 'Item not found' }, { status: 404 })
    }
    return NextResponse.json(item)
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
