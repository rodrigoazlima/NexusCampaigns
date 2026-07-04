import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { VAULT_ROOT, writeFrontmatter } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { filename: string; reason?: string }
    const { filename, reason } = body

    if (!filename) {
      return NextResponse.json({ error: 'filename required' }, { status: 400 })
    }

    const filepath = path.join(VAULT_ROOT, '01-Processing', filename)

    if (!fs.existsSync(filepath)) {
      return NextResponse.json({ error: 'File not found' }, { status: 404 })
    }

    const today = new Date().toISOString().split('T')[0]
    const updates: Record<string, unknown> = {
      status: 'rejected',
      quality: 1,
      reviewed: true,
      updated: today,
    }
    if (reason) updates.rejection_reason = reason

    writeFrontmatter(filepath, updates)

    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
