import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { VAULT_ROOT, writeFrontmatter } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { filename: string; fields: Record<string, unknown> }
    const { filename, fields } = body

    if (!filename || !fields) {
      return NextResponse.json({ error: 'filename and fields required' }, { status: 400 })
    }

    const filepath = path.join(VAULT_ROOT, '01-Processing', filename)

    if (!fs.existsSync(filepath)) {
      return NextResponse.json({ error: 'File not found' }, { status: 404 })
    }

    const today = new Date().toISOString().split('T')[0]
    writeFrontmatter(filepath, { ...fields, updated: today })

    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
