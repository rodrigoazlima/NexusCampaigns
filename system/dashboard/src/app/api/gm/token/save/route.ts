import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, VAULT_ROOT, readGeneratedTokens } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { imageData: string; filename: string; sourcePath?: string }
    const { imageData, filename, sourcePath } = body

    if (!imageData?.startsWith('data:image/png;base64,')) {
      return NextResponse.json({ error: 'Invalid image data' }, { status: 400 })
    }
    if (!filename) {
      return NextResponse.json({ error: 'filename required' }, { status: 400 })
    }

    // Security: filename must be a simple slug, no path traversal
    if (/[/\\]/.test(filename)) {
      return NextResponse.json({ error: 'Invalid filename' }, { status: 400 })
    }

    const genTokens = readGeneratedTokens()

    // Find existing token path for this item via sourcePath lookup
    let tokenAbsPath: string | null = null
    const entry = Object.values(genTokens).find(
      (t) => path.basename(t.sourcePath ?? '').replace(/\.[^.]+$/, '') === filename.replace(/\.[^.]+$/, '') ||
             t.sourcePath?.endsWith(filename)
    )
    if (entry?.tokenPath) {
      const candidate = path.isAbsolute(entry.tokenPath)
        ? entry.tokenPath
        : path.join(PROJECT_ROOT, entry.tokenPath)
      tokenAbsPath = candidate
    }

    // Fallback: place alongside the source file with -token.png suffix
    if (!tokenAbsPath) {
      // Try to find the source image next to where the md file implies
      const slug = filename.replace(/\.md$/, '')
      const outDir = path.join(VAULT_ROOT, '05-Assets', 'tokens')
      fs.mkdirSync(outDir, { recursive: true })
      tokenAbsPath = path.join(outDir, `${slug}.token.png`)
    }

    const buffer = Buffer.from(imageData.replace('data:image/png;base64,', ''), 'base64')
    fs.mkdirSync(path.dirname(tokenAbsPath), { recursive: true })
    fs.writeFileSync(tokenAbsPath, buffer)

    const tokenPath = path.relative(PROJECT_ROOT, tokenAbsPath).replace(/\\/g, '/')

    // Update generated-tokens.json entry
    const genPath = path.join(PROJECT_ROOT, 'agents', 'token', 'state', 'generated-tokens.json')
    try {
      const slug = filename.replace(/\.md$/, '')
      // Find and update existing entry or create one keyed by slug
      let updated = false
      for (const [k, v] of Object.entries(genTokens)) {
        const srcSlug = path.basename(v.sourcePath ?? '').replace(/\.[^.]+$/, '')
        if (srcSlug === slug || k === `path:${v.sourcePath}`) {
          genTokens[k] = { ...v, tokenPath, generatedAt: new Date().toISOString() }
          updated = true
          break
        }
      }
      if (!updated) {
        genTokens[`manual:${slug}`] = {
          sourcePath: sourcePath ?? '',
          tokenPath,
          generatedAt: new Date().toISOString(),
        }
      }
      const tmp = genPath.replace('.json', '.tmp')
      fs.writeFileSync(tmp, JSON.stringify(genTokens, null, 2), 'utf-8')
      fs.renameSync(tmp, genPath)
    } catch {
      // non-fatal — PNG is saved, index update failed
    }

    return NextResponse.json({
      ok: true,
      tokenPath,
      tokenUrl: `/api/image?path=${encodeURIComponent(tokenPath)}`,
    })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
