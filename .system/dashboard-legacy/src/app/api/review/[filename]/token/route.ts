import { NextRequest, NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { VAULT_ROOT, findMarkdownByIdentifier } from '@/lib/vault'

export const dynamic = 'force-dynamic'

function resolveTokenPath(sha256: string | null, sources: string[]): string | null {
  const AUTO_DIR = path.join(VAULT_ROOT, '.system')
  try {
    const raw = fs.readFileSync(path.join(AUTO_DIR, 'generated-tokens.json'), 'utf-8').replace(/^﻿/, '')
    const genTokens = JSON.parse(raw) as {
      version?: number
      tokens: Record<string, { token?: string; tokenPath?: string }>
    }
    const version = genTokens.version ?? 1

    if (version >= 2 && sha256) {
      const entry = genTokens.tokens[sha256]
      const tp = entry?.tokenPath ?? entry?.token
      if (tp) return path.join(VAULT_ROOT, tp.replace(/\//g, path.sep))
    } else {
      for (const src of sources) {
        for (const [key, entry] of Object.entries(genTokens.tokens)) {
          if (path.basename(key) === src || key.endsWith(src)) {
            const tp = entry.token ?? entry.tokenPath
            if (tp) return path.join(VAULT_ROOT, tp.replace(/\//g, path.sep))
          }
        }
      }
    }
  } catch {}
  return null
}

function findSourceInInbox(sources: string[]): string | null {
  const imgDir = path.join(VAULT_ROOT, '00-Inbox', 'images')
  function walk(dir: string): string | null {
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name)
        if (e.isDirectory()) { const f = walk(full); if (f) return f }
        else if (sources.includes(e.name)) return full
      }
    } catch {}
    return null
  }
  return walk(imgDir)
}

export async function POST(req: NextRequest, { params }: { params: { filename: string } }) {
  try {
    const identifier = decodeURIComponent(params.filename)
    const filePath = findMarkdownByIdentifier(identifier)
    if (!filePath || !fs.existsSync(filePath)) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 })
    }

    const { imageData } = await req.json() as { imageData: string }
    if (!imageData?.startsWith('data:image/png;base64,')) {
      return NextResponse.json({ error: 'Invalid image data' }, { status: 400 })
    }

    const raw = fs.readFileSync(filePath, 'utf-8')
    const { data: fm } = matter(raw)
    const sha256 = typeof fm.sha256 === 'string' ? fm.sha256 : null
    const sources: string[] = Array.isArray(fm.source) ? fm.source.map(String) : []

    let tokenAbsPath = resolveTokenPath(sha256, sources)

    if (!tokenAbsPath) {
      const srcAbs = sources.length > 0 ? findSourceInInbox(sources) : null
      if (srcAbs) {
        const ext = path.extname(srcAbs)
        tokenAbsPath = srcAbs.replace(new RegExp(`\\${ext}$`), '') + '-token.png'
      } else {
        const slug = path.basename(filePath, '.md')
        const outDir = path.join(VAULT_ROOT, '05-Assets', 'tokens')
        fs.mkdirSync(outDir, { recursive: true })
        tokenAbsPath = path.join(outDir, `${slug}.token.png`)
      }
    }

    const buffer = Buffer.from(imageData.replace('data:image/png;base64,', ''), 'base64')
    fs.writeFileSync(tokenAbsPath, buffer)

    const relPath = tokenAbsPath.replace(VAULT_ROOT, '').replace(/\\/g, '/').replace(/^\//, '')

    // Update generated-tokens.json so the review page finds the new path
    if (sha256) {
      const AUTO_DIR = path.join(VAULT_ROOT, '.system')
      const tokensFile = path.join(AUTO_DIR, 'generated-tokens.json')
      try {
        const raw2 = fs.existsSync(tokensFile)
          ? fs.readFileSync(tokensFile, 'utf-8').replace(/^﻿/, '')
          : '{}'
        const genTokens = JSON.parse(raw2) as {
          version?: number
          tokens: Record<string, { token?: string; tokenPath?: string }>
        }
        genTokens.version = 2
        genTokens.tokens = genTokens.tokens ?? {}
        genTokens.tokens[sha256] = {
          ...(genTokens.tokens[sha256] ?? {}),
          tokenPath: relPath,
        }
        fs.writeFileSync(tokensFile, JSON.stringify(genTokens, null, 2), 'utf-8')
      } catch { /* non-fatal — token still saved to disk */ }
    }

    return NextResponse.json({
      saved: true,
      tokenUrl: `/api/image?path=${encodeURIComponent('/' + relPath)}`,
      tokenPath: relPath,
    })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
