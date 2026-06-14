import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export interface AgentFiles {
  prompts: string[]   // relative to agent_dir, e.g. "prompts/system.md"
  scripts: string[]   // relative to project_root, e.g. ".agents/vision/tools/classify_images.py"
}

function listFiles(dir: string, exts: string[]): string[] {
  try {
    return fs.readdirSync(dir)
      .filter(f => exts.some(e => f.endsWith(e)))
      .sort()
  } catch {
    return []
  }
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  if (!/^[a-z0-9-]+$/.test(id)) {
    return NextResponse.json({ error: 'Invalid id' }, { status: 400 })
  }

  const agentDir = path.join(PROJECT_ROOT, '.agents', id)
  const promptsDir = path.join(agentDir, 'prompts')
  const toolsDir = path.join(agentDir, 'tools')

  const prompts = listFiles(promptsDir, ['.md', '.txt'])
    .map(f => `prompts/${f}`)

  const scripts = listFiles(toolsDir, ['.py'])
    .filter(f => f !== '__init__.py')
    .map(f => `.agents/${id}/tools/${f}`)

  return NextResponse.json({ prompts, scripts } satisfies AgentFiles)
}
