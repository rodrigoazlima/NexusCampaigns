import path from 'path'
import { spawn } from 'child_process'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, readTokenConfig } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { imagePath: string }
    const { imagePath } = body

    if (!imagePath) {
      return NextResponse.json({ error: 'imagePath required' }, { status: 400 })
    }

    const cfg = readTokenConfig()
    const scriptPath = path.join(PROJECT_ROOT, 'agents', 'token', 'tools', 'generate_tokens.py')

    const tokenPath = await new Promise<string>((resolve, reject) => {
      const args = ['--image', imagePath, '--moldura', cfg.molduraPath]
      const proc = spawn('python', [scriptPath, ...args], {
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

    return NextResponse.json({ ok: true, tokenPath })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
