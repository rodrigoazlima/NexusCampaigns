import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, readTokenConfig } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const ALLOWED_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.avif', '.heic', '.heif', '.jfif'])

export async function POST(req: NextRequest) {
  try {
    const form = await req.formData()
    const file = form.get('file') as File | null
    const sourcePath = form.get('sourcePath') as string | null

    if (!file) return NextResponse.json({ error: 'No file uploaded' }, { status: 400 })
    if (!sourcePath) return NextResponse.json({ error: 'sourcePath required' }, { status: 400 })

    const ext = path.extname(file.name).toLowerCase()
    if (!ALLOWED_EXTS.has(ext)) {
      return NextResponse.json({ error: `Unsupported extension: ${ext}` }, { status: 400 })
    }

    // Save uploaded base image alongside the source with a -base suffix
    const absSource = path.isAbsolute(sourcePath)
      ? sourcePath
      : path.join(PROJECT_ROOT, sourcePath)

    const normalized = path.normalize(absSource)
    if (!normalized.startsWith(path.normalize(PROJECT_ROOT))) {
      return NextResponse.json({ error: 'Forbidden path' }, { status: 403 })
    }

    const dir = path.dirname(absSource)
    const srcStem = path.basename(absSource, path.extname(absSource))
    const baseFilename = `${srcStem}-base${ext}`
    const absBase = path.join(dir, baseFilename)

    fs.mkdirSync(dir, { recursive: true })
    const buffer = Buffer.from(await file.arrayBuffer())
    fs.writeFileSync(absBase, buffer)

    // Run token generation using the uploaded base image
    const cfg = readTokenConfig()

    const tokenPath = await new Promise<string>((resolve, reject) => {
      const args = ['-m', 'nexus.workers.token', '--image', absBase, '--moldura', cfg.molduraPath]
      const proc = spawn('python', args, {
        cwd: PROJECT_ROOT,
        env: { ...process.env },
      })

      let stdout = ''
      let stderr = ''
      proc.stdout.on('data', (d: Buffer) => { stdout += d.toString() })
      proc.stderr.on('data', (d: Buffer) => { stderr += d.toString() })

      proc.on('close', (code) => {
        if (code === 0 && stdout.trim()) {
          resolve(stdout.trim())
        } else {
          reject(new Error(stderr.trim() || `Process exited with code ${code}`))
        }
      })

      proc.on('error', reject)
    })

    // Re-link the generated token back to the original source in generated-tokens.json
    const genPath = path.join(PROJECT_ROOT, 'system', 'state', 'workers', 'token', 'generated-tokens.json')
    try {
      const genTokens = JSON.parse(fs.readFileSync(genPath, 'utf-8')) as Record<string, {
        sourcePath: string; tokenPath: string; generatedAt: string
      }>
      const relSrc = path.relative(PROJECT_ROOT, absSource).replace(/\\/g, '/')
      // Find existing entry by sourcePath and update tokenPath, or create path: key
      let found = false
      for (const [k, v] of Object.entries(genTokens)) {
        if (v.sourcePath === relSrc) {
          genTokens[k] = { ...v, tokenPath, generatedAt: new Date().toISOString() }
          found = true
          break
        }
      }
      if (!found) {
        genTokens[`path:${relSrc}`] = {
          sourcePath: relSrc,
          tokenPath,
          generatedAt: new Date().toISOString(),
        }
      }
      const tmp = genPath.replace('.json', '.tmp')
      fs.writeFileSync(tmp, JSON.stringify(genTokens, null, 2), 'utf-8')
      fs.renameSync(tmp, genPath)
    } catch {
      // non-fatal - token still generated
    }

    return NextResponse.json({ ok: true, tokenPath, basePath: path.relative(PROJECT_ROOT, absBase).replace(/\\/g, '/') })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
