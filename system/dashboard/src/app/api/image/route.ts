import fs from 'fs'
import path from 'path'
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

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const imagePath = searchParams.get('path')

  if (!imagePath) {
    return new NextResponse('Missing path', { status: 400 })
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
    return new NextResponse(buffer, {
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'no-cache',
      },
    })
  } catch {
    return new NextResponse('Not found', { status: 404 })
  }
}
