import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, VAULT_ROOT, readGeneratedTokens, GENERATED_TOKENS_PATH } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { imageData: string; filename: string; sourcePath?: string; existingTokenPath?: string | null }
    const { imageData, filename, sourcePath, existingTokenPath } = body

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
    const slug = filename.replace(/\.md$/, '')

    // Find this item's existing entry. Prefer matching by the tokenPath the
    // client already has (vault filename/source-basename slugs don't follow a
    // consistent convention, e.g. "body-x.md" vs source "x.body.jpg" - string
    // guessing there is unreliable) and fall back to a slug guess otherwise.
    const matchedKey = Object.keys(genTokens).find((k) => {
      const t = genTokens[k]
      if (existingTokenPath && t.tokenPath === existingTokenPath) return true
      const srcBase = path.basename(t.sourcePath ?? '').replace(/\.[^.]+$/, '')
      return srcBase === slug || srcBase.startsWith(`${slug}.`) || t.sourcePath?.endsWith(filename)
    })
    const entry = matchedKey ? genTokens[matchedKey] : undefined

    // Find existing token path for this item via sourcePath lookup
    let tokenAbsPath: string | null = null
    if (entry?.tokenPath) {
      const candidate = path.isAbsolute(entry.tokenPath)
        ? entry.tokenPath
        : path.join(PROJECT_ROOT, entry.tokenPath)
      tokenAbsPath = candidate
    }

    // Fallback: place alongside the source file with -token.png suffix
    if (!tokenAbsPath) {
      const outDir = path.join(VAULT_ROOT, '05-Assets', 'tokens')
      fs.mkdirSync(outDir, { recursive: true })
      tokenAbsPath = path.join(outDir, `${slug}.token.png`)
    }

    const buffer = Buffer.from(imageData.replace('data:image/png;base64,', ''), 'base64')
    fs.mkdirSync(path.dirname(tokenAbsPath), { recursive: true })
    fs.writeFileSync(tokenAbsPath, buffer)

    const tokenPath = path.relative(PROJECT_ROOT, tokenAbsPath).replace(/\\/g, '/')

    // Update generated-tokens.json entry - reuse the same matched key so the
    // index and the file on disk never point at two different tokens. Writes
    // to the same canonical path the token worker itself reads/writes
    // (system/state/workers/token/generated-tokens.json) - a prior version of
    // this route wrote to a legacy path nothing else reads.
    try {
      if (matchedKey) {
        genTokens[matchedKey] = { ...genTokens[matchedKey], tokenPath, generatedAt: new Date().toISOString() }
      } else {
        genTokens[`manual:${slug}`] = {
          sourcePath: sourcePath ?? '',
          tokenPath,
          generatedAt: new Date().toISOString(),
        }
      }
      const tmp = GENERATED_TOKENS_PATH + '.tmp'
      fs.writeFileSync(tmp, JSON.stringify(genTokens, null, 2), 'utf-8')
      fs.renameSync(tmp, GENERATED_TOKENS_PATH)
    } catch {
      // non-fatal - PNG is saved, index update failed
    }

    // Pause the token worker's queue slot for this source so a future
    // reclassification doesn't auto-regenerate over this manual crop fix.
    const srcForPause = sourcePath || entry?.sourcePath
    if (srcForPause) {
      try {
        const queuePath = path.join(PROJECT_ROOT, 'system', 'state', 'inbox-queue.json')
        const queue = JSON.parse(fs.readFileSync(queuePath, 'utf-8'))
        if (queue[srcForPause]?.agents) {
          queue[srcForPause].agents.token = 'paused'
          const tmp = queuePath + '.tmp'
          fs.writeFileSync(tmp, JSON.stringify(queue, null, 2), 'utf-8')
          fs.renameSync(tmp, queuePath)
        }
      } catch {
        // non-fatal - PNG + index are saved, pause is best-effort
      }
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
