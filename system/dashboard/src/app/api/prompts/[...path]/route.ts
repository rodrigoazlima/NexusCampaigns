import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const AGENTS_DIR = path.resolve(path.join(PROJECT_ROOT, 'agents'))

function safePath(segments: string[]): string | null {
  const abs = path.resolve(AGENTS_DIR, ...segments)
  if (!abs.startsWith(AGENTS_DIR + path.sep)) return null
  if (!abs.endsWith('.md')) return null
  return abs
}

type Ctx = { params: Promise<{ path: string[] }> }

export async function GET(_req: NextRequest, { params }: Ctx) {
  const { path: segments } = await params
  const abs = safePath(segments)
  if (!abs) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  if (!fs.existsSync(abs)) return NextResponse.json({ error: 'Not found' }, { status: 404 })
  const content = fs.readFileSync(abs, 'utf-8')
  return new NextResponse(content, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } })
}

export async function PUT(req: NextRequest, { params }: Ctx) {
  const { path: segments } = await params
  const abs = safePath(segments)
  if (!abs) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  try {
    const { content } = await req.json() as { content: string }
    fs.mkdirSync(path.dirname(abs), { recursive: true })
    fs.writeFileSync(abs, content ?? '', 'utf-8')
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

export async function DELETE(_req: NextRequest, { params }: Ctx) {
  const { path: segments } = await params
  const abs = safePath(segments)
  if (!abs) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  if (!fs.existsSync(abs)) return NextResponse.json({ error: 'Not found' }, { status: 404 })
  try {
    fs.unlinkSync(abs)
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
