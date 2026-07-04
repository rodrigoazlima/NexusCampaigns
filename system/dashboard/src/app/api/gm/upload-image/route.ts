import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const ALLOWED_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.avif', '.heic', '.heif', '.jfif'])

export async function POST(req: NextRequest) {
  try {
    const form = await req.formData()
    const file = form.get('file') as File | null
    const targetPath = form.get('targetPath') as string | null

    if (!file) return NextResponse.json({ error: 'No file uploaded' }, { status: 400 })
    if (!targetPath) return NextResponse.json({ error: 'targetPath required' }, { status: 400 })

    const ext = path.extname(file.name).toLowerCase()
    if (!ALLOWED_EXTS.has(ext)) {
      return NextResponse.json({ error: `Unsupported extension: ${ext}` }, { status: 400 })
    }

    const absTarget = path.isAbsolute(targetPath)
      ? targetPath
      : path.join(PROJECT_ROOT, targetPath)

    const normalized = path.normalize(absTarget)
    if (!normalized.startsWith(path.normalize(PROJECT_ROOT))) {
      return NextResponse.json({ error: 'Forbidden path' }, { status: 403 })
    }

    fs.mkdirSync(path.dirname(absTarget), { recursive: true })
    const buffer = Buffer.from(await file.arrayBuffer())
    fs.writeFileSync(absTarget, buffer)

    const relPath = path.relative(PROJECT_ROOT, absTarget).replace(/\\/g, '/')
    return NextResponse.json({ ok: true, path: relPath })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
