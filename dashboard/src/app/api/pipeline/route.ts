import { NextResponse } from 'next/server'
import { readPipeline } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  const data = readPipeline()
  return NextResponse.json(data)
}
