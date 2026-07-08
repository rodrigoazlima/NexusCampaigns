import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const QUEUE_FILE = path.join(PROJECT_ROOT, 'system', 'state', 'inbox-queue.json')

/**
 * Retry button for /queue: flips every 'error' agent slot on the given queue
 * entries back to 'pending', same shape as pause/resume so the runner and
 * per-agent batch queries pick the item back up.
 */
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as { path?: string; paths?: string[] }
    const paths = body.paths ?? (body.path ? [body.path] : [])
    if (paths.length === 0) {
      return NextResponse.json({ error: 'path or paths required' }, { status: 400 })
    }

    const queue = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf-8')) as Record<
      string,
      { agents: Record<string, string> }
    >

    let itemsRetried = 0
    for (const p of paths) {
      const entry = queue[p]
      if (!entry?.agents) continue
      let touched = false
      for (const agent of Object.keys(entry.agents)) {
        if (entry.agents[agent] === 'error') {
          entry.agents[agent] = 'pending'
          touched = true
        }
      }
      if (touched) itemsRetried++
    }

    const tmp = QUEUE_FILE + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(queue, null, 2), 'utf-8')
    fs.renameSync(tmp, QUEUE_FILE)

    return NextResponse.json({ ok: true, itemsRetried })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
