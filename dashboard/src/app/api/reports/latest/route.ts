import { NextResponse } from 'next/server'
import { readLatestReport } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const report = readLatestReport()
  if (!report) return NextResponse.json(null, { status: 404 })
  return NextResponse.json(report)
}
