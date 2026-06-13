import { NextResponse } from 'next/server'
import { parseLog } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const limit    = parseInt(searchParams.get('limit') ?? '200')
  const severity = searchParams.get('severity') // 'error' | 'warning' | null
  const taskId   = searchParams.get('task')

  let logs = parseLog(Math.min(limit * 3, 2000))

  if (severity) logs = logs.filter(l => l.severity === severity)
  if (taskId)   logs = logs.filter(l => l.taskId === taskId)

  return NextResponse.json(logs.slice(0, limit))
}
