import { NextResponse, type NextRequest } from 'next/server'
import { readLogs } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const limit = parseInt(searchParams.get('limit') ?? '100', 10)
  const severity = searchParams.get('severity') ?? undefined
  const task = searchParams.get('task') ?? undefined
  const logs = readLogs({ limit, severity, task })
  return NextResponse.json(logs)
}
