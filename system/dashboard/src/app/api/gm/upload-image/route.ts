import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, findImageByHash, findImageHashClaim, claimImageHash } from '@/lib/vault'

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

    // De-dup against the ingestion-time hash ledger (system/state/image-hashes.json,
    // populated the moment a file is queued) with a fallback to the older
    // processed-images.json (vision-time) lookup for images ingested before
    // that ledger existed. Fail open - a hashing error must not block uploads.
    let hash: string | null = null
    try {
      hash = await hashBuffer(buffer)
      const existing = findImageHashClaim(hash) ?? findImageByHash(hash)
      if (existing) {
        console.log(`upload-image: rejected duplicate ${file.name} - identical to ${existing.path} (hash ${hash.slice(0, 12)}…)`)
        return NextResponse.json({ ok: true, duplicate: true, path: existing.path, originalName: existing.originalName })
      }
    } catch (hashErr) {
      console.error(`upload-image: hash check failed for ${file.name}, proceeding without dedup:`, hashErr)
    }

    fs.mkdirSync(path.dirname(absTarget), { recursive: true })
    fs.writeFileSync(absTarget, buffer)

    const relPath = path.relative(PROJECT_ROOT, absTarget).replace(/\\/g, '/')

    // Claim the hash immediately (rather than waiting for ingestion's next
    // cycle) so a second upload of the same bytes arriving before that cycle
    // runs is still caught here instead of slipping through as a second copy.
    if (hash) {
      try {
        const raced = claimImageHash(hash, relPath)
        if (raced) {
          console.warn(`upload-image: lost dedup race writing ${relPath} - ${raced.path} claimed hash ${hash.slice(0, 12)}… first; both files kept (00-Inbox is never deleted from), ingestion will skip this one downstream`)
        }
      } catch (claimErr) {
        console.error(`upload-image: hash claim failed for ${relPath} (file was still written):`, claimErr)
      }
    }

    console.log(`upload-image: wrote ${relPath}${hash ? ` (hash ${hash.slice(0, 12)}…)` : ' (no hash - dedup check failed)'}`)
    return NextResponse.json({ ok: true, path: relPath })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
