import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const AGENTS_DIR = path.resolve(path.join(PROJECT_ROOT, '.agents'))

function safePath(rel: string): string | null {
  const abs = path.resolve(AGENTS_DIR, ...rel.split('/'))
  if (!abs.startsWith(AGENTS_DIR + path.sep)) return null
  if (!abs.endsWith('.md')) return null
  return abs
}

export async function POST(req: NextRequest) {
  try {
    const { from, to } = await req.json() as { from: string; to: string }
    const fromAbs = safePath(from)
    const toAbs = safePath(to)
    if (!fromAbs || !toAbs) {
      return NextResponse.json({ error: 'Forbidden path' }, { status: 403 })
    }
    if (!fs.existsSync(fromAbs)) {
      return NextResponse.json({ error: 'Source not found' }, { status: 404 })
    }
    if (fs.existsSync(toAbs)) {
      return NextResponse.json({ error: 'Target already exists' }, { status: 409 })
    }
    fs.mkdirSync(path.dirname(toAbs), { recursive: true })
    fs.renameSync(fromAbs, toAbs)
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
