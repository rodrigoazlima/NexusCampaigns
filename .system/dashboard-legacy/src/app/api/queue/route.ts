import { NextResponse } from 'next/server'
import { readQueue } from '@/lib/vault'
import type { QueueStats, QueueItem, FileType, AgentSlotStatus } from '@/lib/types'

export const dynamic = 'force-dynamic'

export async function GET() {
  const raw = readQueue()
  const now = Date.now()

  const items: QueueItem[] = Object.entries(raw).map(([p, v]) => {
    const ingestedAt = v.ingestedAt ?? new Date(0).toISOString()
    const ageMs = now - new Date(ingestedAt).getTime()
    const agents = v.agents as Record<string, AgentSlotStatus>
    const hasPending = Object.values(agents).some(s => s === 'pending')
    return {
      path: p,
      ingestedAt,
      type: (v.type ?? 'other') as FileType,
      agents,
      ageMs,
      isStuck: hasPending && ageMs > 2 * 3600_000,
    }
  })

  const byType: Record<FileType, number> = { image: 0, document: 0, other: 0 }
  items.forEach(i => { byType[i.type] = (byType[i.type] ?? 0) + 1 })

  const pending = items.filter(i => Object.values(i.agents).some(s => s === 'pending')).length
  const done    = items.filter(i => Object.values(i.agents).every(s => s === 'done' || s === 'skip')).length
  const stuck   = items.filter(i => i.isStuck).length

  const stats: QueueStats = {
    total: items.length,
    byType,
    byStatus: { pending, done, stuck },
    items: items.sort((a, b) => new Date(b.ingestedAt).getTime() - new Date(a.ingestedAt).getTime()),
  }

  return NextResponse.json(stats)
}
