import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

function getConfigPath(id: string): string | null {
  if (id === 'runtime') {
    return path.join(PROJECT_ROOT, '.agents', 'runtime', 'runtime-config.json')
  }
  if (!/^[a-z0-9-]+$/.test(id)) return null
  return path.join(PROJECT_ROOT, '.agents', id, 'agent.json')
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const configPath = getConfigPath(id)
  if (!configPath) {
    return NextResponse.json({ error: 'Invalid id' }, { status: 400 })
  }
  try {
    const raw = fs.readFileSync(configPath, 'utf-8')
    return NextResponse.json(JSON.parse(raw))
  } catch {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }
}

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

type DispatchConfig = Record<string, unknown>

/** Collect all dispatch configs (primary + fallback) from a parsed agent.json body. */
function collectDispatches(body: Record<string, unknown>): DispatchConfig[] {
  const dispatches: DispatchConfig[] = []
  const tasks = body.tasks as Record<string, Record<string, unknown>> | undefined
  if (!tasks) return dispatches
  for (const task of Object.values(tasks)) {
    if (task.dispatch) dispatches.push(task.dispatch as DispatchConfig)
    if (task.fallback_dispatch) dispatches.push(task.fallback_dispatch as DispatchConfig)
  }
  return dispatches
}

/**
 * Validate that prompt/script files referenced in a dispatch config actually exist.
 * Returns an error string, or null if valid.
 */
function validateDispatch(dispatch: DispatchConfig, agentId: string): string | null {
  const type = dispatch.type as string
  const agentDir = path.join(PROJECT_ROOT, '.agents', agentId)

  // LLM-type dispatches: system_file and prompt_file must exist if set
  const llmCfgKey: Record<string, string> = {
    'lm-studio':      'lm_studio',
    'openai-api':     'openai_api',
    'claude-api':     'claude_api',
    'gemini-api':     'gemini_api',
    'openrouter-api': 'openrouter_api',
  }
  if (llmCfgKey[type]) {
    const cfg = dispatch[llmCfgKey[type]] as DispatchConfig | undefined
    if (cfg) {
      for (const field of ['system_file', 'prompt_file'] as const) {
        const rel = cfg[field] as string | null | undefined
        if (!rel) continue  // null/undefined = no prompt file, allowed
        const abs = path.join(agentDir, rel)
        if (!fs.existsSync(abs)) {
          return `${field} "${rel}" does not exist in .agents/${agentId}/`
        }
      }
    }
  }

  // claude-code / codex-cli: prompt_file must exist if set
  const fileCfgKey: Record<string, string> = {
    'claude-code': 'claude_code',
    'codex-cli':   'codex_cli',
  }
  if (fileCfgKey[type]) {
    const cfg = dispatch[fileCfgKey[type]] as DispatchConfig | undefined
    if (cfg) {
      const rel = cfg['prompt_file'] as string | null | undefined
      if (rel) {
        const abs = path.join(agentDir, rel)
        if (!fs.existsSync(abs)) {
          return `prompt_file "${rel}" does not exist in .agents/${agentId}/`
        }
      }
    }
  }

  // cli: args[0] (script path) must exist relative to project_root
  if (type === 'cli') {
    const cfg = dispatch['cli'] as DispatchConfig | undefined
    const args = cfg?.args as string[] | undefined
    const script = args?.[0]
    if (script) {
      const abs = path.join(PROJECT_ROOT, script)
      if (!fs.existsSync(abs)) {
        return `cli script "${script}" does not exist`
      }
    }
  }

  return null
}

// ---------------------------------------------------------------------------
// PUT — save agent.json with validation
// ---------------------------------------------------------------------------

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const configPath = getConfigPath(id)
  if (!configPath) {
    return NextResponse.json({ error: 'Invalid id' }, { status: 400 })
  }
  try {
    const body = await req.json() as Record<string, unknown>

    // Validate all dispatch configs before writing
    if (id !== 'runtime') {
      for (const dispatch of collectDispatches(body)) {
        const err = validateDispatch(dispatch, id)
        if (err) {
          return NextResponse.json({ error: err }, { status: 422 })
        }
      }
    }

    fs.writeFileSync(configPath, JSON.stringify(body, null, 2), 'utf-8')
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
