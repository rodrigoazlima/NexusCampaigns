import { NextResponse } from 'next/server'
import { readVaultStats } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const stats = readVaultStats()
  return NextResponse.json(stats)
}
