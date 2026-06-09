import { NextRequest, NextResponse } from 'next/server'
import { execSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { readTasks, VAULT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'
export const maxDuration = 300

export async function POST(req: NextRequest) {
  const { agentId } = await req.json() as { agentId: string }
  if (!agentId) return NextResponse.json({ error: 'agentId required' }, { status: 400 })

  const tasks = readTasks()
  const task = tasks.find(t => t.id === agentId)
  if (!task) return NextResponse.json({ error: `Agent "${agentId}" not found` }, { status: 404 })

  const scriptPath = path.join(VAULT_ROOT, '.system', task.script)
  if (!fs.existsSync(scriptPath)) {
    return NextResponse.json({ error: `Script not found: ${task.script}` }, { status: 404 })
  }

  const isPy  = task.script.endsWith('.py')
  const isPs1 = task.script.endsWith('.ps1')
  let cmd: string
  if (isPy)       cmd = `python "${scriptPath}"`
  else if (isPs1) cmd = `pwsh -ExecutionPolicy Bypass -File "${scriptPath}"`
  else            return NextResponse.json({ error: 'Unknown script type' }, { status: 400 })

  try {
    const output = execSync(cmd, {
      cwd: VAULT_ROOT,
      timeout: 290_000,
      maxBuffer: 10 * 1024 * 1024,
      encoding: 'utf-8',
    })
    return NextResponse.json({ success: true, output: String(output ?? '').slice(-3000) })
  } catch (e: unknown) {
    const err = e as { message?: string; stdout?: Buffer | string; stderr?: Buffer | string; status?: number }
    const out = [err.stdout, err.stderr].filter(Boolean).map(b => String(b)).join('\n').slice(-3000)
    return NextResponse.json({ success: false, error: err.message ?? 'Script failed', output: out }, { status: 500 })
  }
}
