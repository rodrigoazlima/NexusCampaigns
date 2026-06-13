import { NextResponse } from 'next/server'
import { getReviewItems } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  return NextResponse.json(getReviewItems())
}
