import fs from 'fs'
import path from 'path'
import crypto from 'crypto'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, isTokenPath } from '@/lib/vault'

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
const IMMUTABLE = 'public, max-age=31536000, immutable'

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
      return new NextResponse(buffer, {
        headers: { 'Content-Type': 'image/webp', 'Cache-Control': IMMUTABLE },
      })
    } catch {
      // no thumb yet — serve the original below
    }
  }

  let absolutePath = path.isAbsolute(imagePath)
    ? imagePath
    : path.join(PROJECT_ROOT, imagePath)

  // ponytail: some drafts have a `source:` path missing its leading dot
  // (`knowledge-base/...` instead of `.knowledge-base/...`) from a prior
  // agent bug — retry with the dot before 404ing.
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
    // 00-Inbox is read-only by vault rules, so originals there never change;
    // generated tokens (*-token.png) can be regenerated in place — keep those fresh.
    const inInbox = normalized.replace(/\\/g, '/').includes('/00-Inbox/')
    const cacheControl = inInbox && !isTokenPath(normalized) ? IMMUTABLE : 'no-cache'
    return new NextResponse(buffer, {
      headers: {
        'Content-Type': contentType,
        'Cache-Control': cacheControl,
      },
    })
  } catch {
    return new NextResponse('Not found', { status: 404 })
  }
}
