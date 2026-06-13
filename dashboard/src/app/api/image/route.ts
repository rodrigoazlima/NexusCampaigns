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

  const absolutePath = path.isAbsolute(imagePath)
    ? imagePath
    : path.join(PROJECT_ROOT, imagePath)

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
        'Cache-Control': 'public, max-age=3600',
      },
    })
  } catch {
    return new NextResponse('Not found', { status: 404 })
  }
}
