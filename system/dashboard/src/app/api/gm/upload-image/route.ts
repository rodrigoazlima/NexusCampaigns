import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, findImageByHash } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const ALLOWED_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.avif', '.heic', '.heif', '.jfif'])

/** blake2b-32 digest matching nexus.shared.hashing (same algorithm as processed-images.json keys). */
function hashBuffer(buf: Buffer): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn('python', ['-m', 'nexus.shared.hashing'], { cwd: PROJECT_ROOT, env: { ...process.env } })
    let stdout = ''
    let stderr = ''
    proc.stdout.on('data', (d: Buffer) => { stdout += d.toString() })
    proc.stderr.on('data', (d: Buffer) => { stderr += d.toString() })
    proc.on('close', (code) => {
      if (code === 0 && stdout.trim()) resolve(stdout.trim())
      else reject(new Error(stderr.trim() || `hashing exited with code ${code}`))
    })
    proc.on('error', reject)
    proc.stdin.end(buf)
  })
}

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

    const buffer = Buffer.from(await file.arrayBuffer())

    // De-dup against already-ingested images (system state: processed-images.json,
    // keyed by content hash). Fail open — a hashing error must not block uploads.
    try {
      const hash = await hashBuffer(buffer)
      const existing = findImageByHash(hash)
      if (existing) {
        return NextResponse.json({ ok: true, duplicate: true, path: existing.path, originalName: existing.originalName })
      }
    } catch (hashErr) {
      console.error('upload-image: hash check failed, proceeding without dedup:', hashErr)
    }

    fs.mkdirSync(path.dirname(absTarget), { recursive: true })
    fs.writeFileSync(absTarget, buffer)

    const relPath = path.relative(PROJECT_ROOT, absTarget).replace(/\\/g, '/')
    return NextResponse.json({ ok: true, path: relPath })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
