import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, VAULT_ROOT, writeFrontmatter } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const QUEUE_FILE = path.join(PROJECT_ROOT, 'system', 'state', 'inbox-queue.json')
const PROCESSING = path.join(VAULT_ROOT, '01-Processing')

// Agents whose work lives in the generated drafts — reprocessing these also
// flags the source's drafts as needs_reprocessing (reuses the existing flag).
const DRAFT_AGENTS = new Set(['lore', 'wiki', 'classification', 'review'])

/**
 * Flag a single agent of a queued source for re-run / reprocessing.
 *  - resets that agent's slot to pending so the agent picks the item up again
 *  - bumps the per-agent manual re-run counter on the entry
 *  - for draft-producing agents, reuses needs_reprocessing on this source's drafts
 */
export async function POST(req: NextRequest) {
  try {
    const { path: srcPath, agent } = (await req.json()) as { path: string; agent: string }
    if (!srcPath || !agent) {
      return NextResponse.json({ error: 'path and agent required' }, { status: 400 })
    }
    if (agent === 'ingestion') {
      return NextResponse.json({ error: 'ingestion cannot be re-run' }, { status: 400 })
    }

    const queue = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf-8')) as Record<
      string,
      { agents: Record<string, string>; reruns?: Record<string, number> }
    >
    const entry = queue[srcPath]
    if (!entry) {
      return NextResponse.json({ error: 'Not in queue' }, { status: 404 })
    }
    if (!(agent in entry.agents)) {
      return NextResponse.json({ error: `Unknown agent: ${agent}` }, { status: 400 })
    }

    // Reset the agent's slot so it re-runs.
    entry.agents[agent] = 'pending'

    // Bump the per-agent manual re-run counter.
    const reruns = entry.reruns && typeof entry.reruns === 'object' ? entry.reruns : {}
    reruns[agent] = (reruns[agent] ?? 0) + 1
    entry.reruns = reruns

    const tmp = QUEUE_FILE + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(queue, null, 2), 'utf-8')
    fs.renameSync(tmp, QUEUE_FILE)

    // Draft-producing agents: reuse the existing needs_reprocessing flag.
    let draftsFlagged = 0
    if (DRAFT_AGENTS.has(agent)) {
      const norm = srcPath.replace(/\\/g, '/')
      const today = new Date().toISOString().split('T')[0]
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
    }

    return NextResponse.json({ ok: true, agent, reruns: reruns[agent], draftsFlagged })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
