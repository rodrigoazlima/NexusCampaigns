import fs from 'fs'
import path from 'path'
import crypto from 'crypto'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const MIME: Record<string, string> = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.bmp': 'image/bmp',
  '.svg': 'image/svg+xml',
}

const THUMBS_DIR = path.join(PROJECT_ROOT, 'system', 'state', 'thumbs')

// Vault filenames aren't stable identities: the vision agent renames
// uploads in place on slug collision (agents/vision/tools/classify_images.py
// _resolve_image_target), so the same path can hold different bytes over a
// vault's lifetime. `immutable`/long max-age caches by path and never
// revalidates - that lied about content that does change, and caused
// browsers to keep showing a stale image forever after a collision-rename.
// Content hash as the ETag makes the browser revalidate cheaply (304) on
// every request instead of trusting the path blindly.
function respondWithEtag(req: NextRequest, buffer: Buffer, contentType: string): NextResponse {
  const etag = `"${crypto.createHash('sha256').update(buffer).digest('hex')}"`
  if (req.headers.get('if-none-match') === etag) {
    return new NextResponse(null, { status: 304, headers: { ETag: etag, 'Cache-Control': 'no-cache' } })
  }
  return new NextResponse(new Uint8Array(buffer), {
    headers: { 'Content-Type': contentType, ETag: etag, 'Cache-Control': 'no-cache' },
  })
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const imagePath = searchParams.get('path')

  if (!imagePath) {
    return new NextResponse('Missing path', { status: 400 })
  }

  // Pre-generated thumbnail (agents/thumbnails), keyed by sha1 of the
  // normalized queue path. Missing thumb falls through to the original.
  if (searchParams.get('thumb')) {
    const key = crypto.createHash('sha1').update(imagePath.replace(/\\/g, '/')).digest('hex')
    const thumbPath = path.join(THUMBS_DIR, `${key}.webp`)
    try {
      const buffer = fs.readFileSync(thumbPath)
      return respondWithEtag(req, buffer, 'image/webp')
    } catch {
      // no thumb yet - serve the original below
    }
  }

  let absolutePath = path.isAbsolute(imagePath)
    ? imagePath
    : path.join(PROJECT_ROOT, imagePath)

  // ponytail: some drafts have a `source:` path missing its leading dot
  // (`knowledge-base/...` instead of `.knowledge-base/...`) from a prior
  // agent bug - retry with the dot before 404ing.
  if (!fs.existsSync(absolutePath) && !path.isAbsolute(imagePath) && imagePath.startsWith('knowledge-base/')) {
    absolutePath = path.join(PROJECT_ROOT, `.${imagePath}`)
  }

  const normalized = path.normalize(absolutePath)
  const projectNormalized = path.normalize(PROJECT_ROOT)
  if (!normalized.startsWith(projectNormalized)) {
    return new NextResponse('Forbidden', { status: 403 })
  }

  try {
    const ext = path.extname(absolutePath).toLowerCase()
    const contentType = MIME[ext] ?? 'application/octet-stream'
    const buffer = fs.readFileSync(absolutePath)
    return respondWithEtag(req, buffer, contentType)
  } catch {
    return new NextResponse('Not found', { status: 404 })
  }
}
