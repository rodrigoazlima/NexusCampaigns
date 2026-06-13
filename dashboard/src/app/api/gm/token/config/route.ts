import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, readTokenConfig, writeTokenConfig } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    return NextResponse.json(readTokenConfig())
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { molduraPath: string }
    const { molduraPath } = body

    if (!molduraPath) {
      return NextResponse.json({ error: 'molduraPath required' }, { status: 400 })
    }

    const absPath = path.join(PROJECT_ROOT, molduraPath)
    if (!fs.existsSync(absPath)) {
      return NextResponse.json({ error: 'Frame file not found' }, { status: 404 })
    }

    writeTokenConfig({ molduraPath })
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
