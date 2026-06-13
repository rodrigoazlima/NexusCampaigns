import { NextResponse } from 'next/server'
import { readQueue } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const data = readQueue()
  return NextResponse.json(data)
}
