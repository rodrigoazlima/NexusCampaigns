import { execFile } from 'child_process'
import path from 'path'
import { promisify } from 'util'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const execFileAsync = promisify(execFile)

const RUNNER = path.join(PROJECT_ROOT, 'agents', 'runtime', 'tools', 'runner.py')
const PYTHON = 'python'
const REPAIR_TIMEOUT_MS = 60_000

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({})) as { agent?: string; error?: string }

    try {
      const { stdout, stderr } = await execFileAsync(
        PYTHON,
        [RUNNER, '--task', 'repair-agent', '--force'],
        { timeout: REPAIR_TIMEOUT_MS, env: { ...process.env } }
      )
      return NextResponse.json({ ok: true, agent: body.agent ?? null, stdout, stderr })
    } catch (execErr) {
      return NextResponse.json({ ok: false, error: String(execErr) }, { status: 500 })
    }
  } catch (err) {
    return NextResponse.json({ ok: false, error: String(err) }, { status: 500 })
  }
}
