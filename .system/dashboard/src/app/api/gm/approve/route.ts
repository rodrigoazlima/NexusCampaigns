import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { VAULT_ROOT, writeFrontmatter, promoteToLibrary } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { filename: string; quality: number }
    const { filename, quality } = body

    if (!filename) {
      return NextResponse.json({ error: 'filename required' }, { status: 400 })
    }

    const filepath = path.join(VAULT_ROOT, '01-Processing', filename)

    if (!fs.existsSync(filepath)) {
      return NextResponse.json({ error: 'File not found' }, { status: 404 })
    }

    const today = new Date().toISOString().split('T')[0]
    writeFrontmatter(filepath, {
      status: 'approved',
      reviewed: true,
      quality: typeof quality === 'number' ? quality : 7,
      updated: today,
    })

    promoteToLibrary(filepath)

    return NextResponse.json({ ok: true, promoted: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
