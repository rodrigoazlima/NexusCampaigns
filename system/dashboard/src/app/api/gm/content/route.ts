import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { VAULT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const filename = searchParams.get('filename')

  if (!filename) {
    return NextResponse.json({ error: 'filename required' }, { status: 400 })
  }

  const draftPath = path.join(VAULT_ROOT, '01-Processing', filename)
  const libraryPath = path.join(VAULT_ROOT, '02-Library', filename)
  const filepath = fs.existsSync(draftPath) ? draftPath : libraryPath

  if (!fs.existsSync(filepath)) {
    return NextResponse.json({ error: 'File not found' }, { status: 404 })
  }

  const content = fs.readFileSync(filepath, 'utf-8')
  return NextResponse.json({ content })
}

export async function PUT(req: NextRequest) {
  try {
    const body = await req.json() as { filename: string; content: string }
    const { filename, content } = body

    if (!filename || content === undefined) {
      return NextResponse.json({ error: 'filename and content required' }, { status: 400 })
    }

    const filepath = path.join(VAULT_ROOT, '01-Processing', filename)

    if (!fs.existsSync(filepath)) {
      return NextResponse.json({ error: 'File not found' }, { status: 404 })
    }

    fs.writeFileSync(filepath, content, 'utf-8')
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
