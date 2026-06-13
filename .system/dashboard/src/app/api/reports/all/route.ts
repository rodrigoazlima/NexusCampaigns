import { NextResponse } from 'next/server'
import { readAllReports } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const reports = readAllReports()
  return NextResponse.json(reports)
}
