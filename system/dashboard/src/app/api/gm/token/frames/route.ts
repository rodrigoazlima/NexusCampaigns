import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { VAULT_ROOT, PROJECT_ROOT, readTokenConfig, writeTokenConfig } from '@/lib/vault'

export const dynamic = 'force-dynamic'

function listFrames(): { name: string; url: string }[] {
  const framesDir = path.join(VAULT_ROOT, '05-Assets', 'tokens', 'frames')
  try {
    return fs
      .readdirSync(framesDir)
      .filter((f) => /\.(png|jpg|webp)$/i.test(f))
      .sort((a, b) => {
        const na = parseInt(a.replace(/\D+/g, '') || '999')
        const nb = parseInt(b.replace(/\D+/g, '') || '999')
        return na - nb
      })
      .map((f) => {
        const rel = path.relative(PROJECT_ROOT, path.join(framesDir, f)).replace(/\\/g, '/')
        return { name: f, url: `/api/image?path=${encodeURIComponent(rel)}` }
      })
  } catch {
    return []
  }
}

export async function GET() {
  const cfg = readTokenConfig()
  const defaultFrame = path.basename(cfg.molduraPath)
  return NextResponse.json({ frames: listFrames(), defaultFrame })
}

export async function PATCH(req: NextRequest) {
  try {
    const { defaultFrame } = await req.json() as { defaultFrame: string }
    if (!defaultFrame) return NextResponse.json({ error: 'defaultFrame required' }, { status: 400 })

    const framesDir = path.join(VAULT_ROOT, '05-Assets', 'tokens', 'frames')
    const absFrame = path.join(framesDir, defaultFrame)
    if (!fs.existsSync(absFrame)) {
      return NextResponse.json({ error: 'Frame not found' }, { status: 404 })
    }

    const molduraPath = path.relative(PROJECT_ROOT, absFrame).replace(/\\/g, '/')
    writeTokenConfig({ molduraPath })
    return NextResponse.json({ ok: true, defaultFrame })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
