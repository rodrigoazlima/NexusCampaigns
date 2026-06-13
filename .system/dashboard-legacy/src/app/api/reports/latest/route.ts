import { NextResponse } from 'next/server'
import { latestReport } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const report = latestReport()
  if (!report) return NextResponse.json({ error: 'No reports found' }, { status: 404 })
  return NextResponse.json(report)
}
