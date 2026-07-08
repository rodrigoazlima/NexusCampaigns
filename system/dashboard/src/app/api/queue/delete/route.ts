import fs from 'fs'
import path from 'path'
import crypto from 'crypto'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const QUEUE_FILE = path.join(PROJECT_ROOT, 'system', 'state', 'inbox-queue.json')
const THUMBS_DIR = path.join(PROJECT_ROOT, 'system', 'state', 'thumbs')

const unlinkIfExists = (p: string) => {
  try {
    fs.unlinkSync(p)
    return true
  } catch {
    return false
  }
}

/**
 * Delete button for /queue: removes a queue item's source file, its
 * generated token image, its cached thumbnail, and the queue entry itself.
 * Leaves any 01-Processing draft untouched — that's reviewable content, not
 * a generated pipeline artifact.
 */
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as { path?: string; paths?: string[] }
    const paths = body.paths ?? (body.path ? [body.path] : [])
    if (paths.length === 0) {
      return NextResponse.json({ error: 'path or paths required' }, { status: 400 })
    }

    const queue = JSON.parse(fs.readFileSync(QUEUE_FILE, 'utf-8')) as Record<string, unknown>

    let itemsDeleted = 0
    for (const p of paths) {
      if (!(p in queue)) continue

      const absolutePath = path.join(PROJECT_ROOT, p)
      const normalized = path.normalize(absolutePath)
      if (!normalized.startsWith(path.normalize(PROJECT_ROOT))) continue

      unlinkIfExists(absolutePath)

      const ext = path.extname(absolutePath)
      const base = absolutePath.slice(0, -ext.length)
      unlinkIfExists(`${base}-token.png`)

      const key = crypto.createHash('sha1').update(p.replace(/\\/g, '/')).digest('hex')
      unlinkIfExists(path.join(THUMBS_DIR, `${key}.webp`))

      delete queue[p]
      itemsDeleted++
    }

    const tmp = QUEUE_FILE + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify(queue, null, 2), 'utf-8')
    fs.renameSync(tmp, QUEUE_FILE)

    return NextResponse.json({ ok: true, itemsDeleted })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
