import { NextResponse } from 'next/server'
import { readAgents } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const agents = readAgents()
  return NextResponse.json(agents)
}
