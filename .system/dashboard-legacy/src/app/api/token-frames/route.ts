import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import { VAULT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const TOKEN_CONFIG_PATH = path.join(VAULT_ROOT, '.system', '10-generate-tokens.json')
const FALLBACK_DEFAULT = 'moldura_default.png'

function readDefaultFrame(): string {
  try {
    const cfg = JSON.parse(fs.readFileSync(TOKEN_CONFIG_PATH, 'utf-8'))
    // moldura value is a vault-relative path like "00-Inbox\tokens\Molduras\moldura_default.png"
    return path.basename(cfg.moldura ?? FALLBACK_DEFAULT)
  } catch {
    return FALLBACK_DEFAULT
  }
}

export async function PATCH(req: Request) {
  try {
    const { defaultFrame } = await req.json() as { defaultFrame: string }
    if (!defaultFrame) return NextResponse.json({ error: 'defaultFrame required' }, { status: 400 })
    let cfg: Record<string, unknown> = {}
    try { cfg = JSON.parse(fs.readFileSync(TOKEN_CONFIG_PATH, 'utf-8')) } catch { /* new file */ }
    cfg.moldura = `00-Inbox\\tokens\\Molduras\\${defaultFrame}`
    fs.writeFileSync(TOKEN_CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf-8')
    return NextResponse.json({ ok: true, defaultFrame })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

export async function GET() {
  const molduraDir = path.join(VAULT_ROOT, '00-Inbox', 'tokens', 'Molduras')
  try {
    const files = fs.readdirSync(molduraDir)
      .filter(f => /\.(png|jpg|jpeg)$/i.test(f))
      .sort((a, b) => {
        const na = parseInt(a.match(/\((\d+)\)/)?.[1] ?? '999')
        const nb = parseInt(b.match(/\((\d+)\)/)?.[1] ?? '999')
        return na - nb
      })
    const frames = files.map(f => ({
      name: f,
      url: `/api/image?path=${encodeURIComponent('/00-Inbox/tokens/Molduras/' + f)}`,
    }))
    return NextResponse.json({ frames, defaultFrame: readDefaultFrame() })
  } catch {
    return NextResponse.json({ frames: [], defaultFrame: FALLBACK_DEFAULT })
  }
}
