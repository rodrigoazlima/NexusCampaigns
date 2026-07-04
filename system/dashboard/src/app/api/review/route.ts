import { NextResponse } from 'next/server'
import { readReviewItems } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const items = readReviewItems()
  return NextResponse.json(items)
}
