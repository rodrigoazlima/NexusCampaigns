import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const QUEUE_FILE = path.join(PROJECT_ROOT, 'system', 'state', 'inbox-queue.json')

/**
 * Pause button for /queue: flips every 'pending' agent slot on the given
 * queue entries to 'paused'. Runner precondition checks and each agent's own
 * batch-selection query only ever pick up slots literally equal to
 * 'pending' (agents/runtime/tools/runner.py::_inbox_has_slot and friends),
 * so this alone removes the item from active processing - no Python-side
 * change needed. Reprocessing an agent (existing per-agent button) sets the
 * slot back to 'pending', which doubles as resume.
 */
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as { path?: string; paths?: string[]; agent?: string }
    const paths = body.paths ?? (body.path ? [body.path] : [])
    if (paths.length === 0) {
      return NextResponse.json({ error: 'path or paths required' }, { status: 400 })
    }

    const queue = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf-8')) as Record<
      string,
      { agents: Record<string, string> }
    >

    let itemsPaused = 0
    for (const p of paths) {
      const entry = queue[p]
      if (!entry?.agents) continue
      let touched = false
      // When `agent` is given (e.g. an agent detail page), only that slot is
      // touched - the other agents on this queue entry keep processing.
      const slots = body.agent ? [body.agent] : Object.keys(entry.agents)
      for (const agent of slots) {
        if (entry.agents[agent] === 'pending') {
          entry.agents[agent] = 'paused'
          touched = true
        }
      }
      if (touched) itemsPaused++
    }

    const tmp = QUEUE_FILE + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(queue, null, 2), 'utf-8')
    fs.renameSync(tmp, QUEUE_FILE)

    return NextResponse.json({ ok: true, itemsPaused })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
