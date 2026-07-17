import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const QUEUE_FILE = path.join(PROJECT_ROOT, 'system', 'state', 'inbox-queue.json')

const IMAGE_SLOTS = {
  ingestion: 'done',
  vision: 'pending',
  lore: 'pending',
  classification: 'pending',
  wiki: 'skip',
  wikilink: 'skip',
  token: 'pending',
  review: 'pending',
} as const

export async function POST(req: NextRequest) {
  try {
    const { path: vaultPath } = (await req.json()) as { path: string }
    if (!vaultPath) return NextResponse.json({ error: 'path required' }, { status: 400 })

    const normalized = vaultPath.replace(/\\/g, '/')
    if (!normalized.startsWith('.knowledge-base/00-Inbox/')) {
      return NextResponse.json({ error: 'path must be under .knowledge-base/00-Inbox/' }, { status: 400 })
    }

    let queue: Record<string, unknown> = {}
    try {
      queue = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf-8'))
    } catch {
      // queue file missing - start fresh
    }

    if (normalized in queue) {
      return NextResponse.json({ ok: true, skipped: true })
    }

    const entry = {
      ingestedAt: new Date().toISOString(),
      type: 'image',
      agents: { ...IMAGE_SLOTS },
      reruns: {},
    }

    // Prepend so new item is first in insertion order (top of pending bucket)
    const updated = { [normalized]: entry, ...queue }
    const tmp = QUEUE_FILE + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(updated, null, 2), 'utf-8')
    fs.renameSync(tmp, QUEUE_FILE)

    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
