import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

function getConfigPath(id: string): string | null {
  if (id === 'runtime') {
    return path.join(PROJECT_ROOT, '.agents', 'runtime', 'runtime-config.json')
  }
  if (!/^[a-z0-9-]+$/.test(id)) return null
  return path.join(PROJECT_ROOT, '.agents', id, 'agent.json')
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const configPath = getConfigPath(id)
  if (!configPath) {
    return NextResponse.json({ error: 'Invalid id' }, { status: 400 })
  }
  try {
    const raw = fs.readFileSync(configPath, 'utf-8')
    return NextResponse.json(JSON.parse(raw))
  } catch {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }
}

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const configPath = getConfigPath(id)
  if (!configPath) {
    return NextResponse.json({ error: 'Invalid id' }, { status: 400 })
  }
  try {
    const body = await req.json()
    fs.writeFileSync(configPath, JSON.stringify(body, null, 2), 'utf-8')
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
