import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, VAULT_ROOT, writeFrontmatter } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const QUEUE_FILE = path.join(PROJECT_ROOT, '.system', 'state', 'inbox-queue.json')
const PROCESSING = path.join(VAULT_ROOT, '01-Processing')

/**
 * Flag a queued source for re-run / reprocessing.
 *  - resets completed agent slots (done -> pending) so the pipeline re-runs it
 *    (ingestion stays done; skip slots are left untouched)
 *  - bumps the per-entry manual re-run counter
 *  - reuses the existing needs_reprocessing flag on every draft from this source
 */
export async function POST(req: NextRequest) {
  try {
    const { path: srcPath } = (await req.json()) as { path: string }
    if (!srcPath) {
      return NextResponse.json({ error: 'path required' }, { status: 400 })
    }

    const queue = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf-8')) as Record<
      string,
      { agents: Record<string, string>; reruns?: number }
    >
    const entry = queue[srcPath]
    if (!entry) {
      return NextResponse.json({ error: 'Not in queue' }, { status: 404 })
    }

    // Reset completed slots so agents pick the item up again.
    let slotsReset = 0
    for (const [agent, status] of Object.entries(entry.agents)) {
      if (agent !== 'ingestion' && status === 'done') {
        entry.agents[agent] = 'pending'
        slotsReset++
      }
    }
    entry.reruns = (entry.reruns ?? 0) + 1

    const tmp = QUEUE_FILE + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(queue, null, 2), 'utf-8')
    fs.renameSync(tmp, QUEUE_FILE)

    // Reuse the existing reprocess flag on every draft generated from this source.
    const norm = srcPath.replace(/\\/g, '/')
    const today = new Date().toISOString().split('T')[0]
    let draftsFlagged = 0
    try {
      for (const file of fs.readdirSync(PROCESSING)) {
        if (!file.endsWith('.md')) continue
        const fp = path.join(PROCESSING, file)
        const { data } = matter(fs.readFileSync(fp, 'utf-8'))
        const sources: string[] = Array.isArray(data.source) ? data.source : []
        if (sources.some((s) => String(s).replace(/\\/g, '/') === norm)) {
          writeFrontmatter(fp, { needs_reprocessing: true, updated: today })
          draftsFlagged++
        }
      }
    } catch {
      // 01-Processing may not exist — slot reset already persisted
    }

    return NextResponse.json({ ok: true, reruns: entry.reruns, slotsReset, draftsFlagged })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
