import { NextRequest, NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import { VAULT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const ALLOWED_EXTS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'])

const MIME: Record<string, string> = {
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
  '.gif': 'image/gif',  '.webp': 'image/webp', '.svg': 'image/svg+xml',
}

export async function GET(req: NextRequest) {
  const imgPath = req.nextUrl.searchParams.get('path')
  if (!imgPath) return NextResponse.json({ error: 'Missing path' }, { status: 400 })

  const ext = path.extname(imgPath).toLowerCase()
  if (!ALLOWED_EXTS.has(ext)) return NextResponse.json({ error: 'Not allowed' }, { status: 403 })

  const abs = path.normalize(path.join(VAULT_ROOT, imgPath.replace(/^\//, '')))
  if (!abs.startsWith(path.normalize(VAULT_ROOT))) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  if (!fs.existsSync(abs)) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  const buffer = fs.readFileSync(abs)
  return new NextResponse(buffer, {
    headers: {
      'Content-Type': MIME[ext] ?? 'application/octet-stream',
      'Cache-Control': 'public, max-age=3600',
    },
  })
}
