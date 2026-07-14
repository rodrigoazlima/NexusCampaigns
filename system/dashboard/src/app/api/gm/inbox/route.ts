import { readInboxImages } from '@/lib/vault'
import { NextRequest, NextResponse } from 'next/server'
import type { InboxPage } from '@/lib/types'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const offset = Math.max(0, Number(searchParams.get('offset')) || 0)
  const limit = Math.min(200, Math.max(1, Number(searchParams.get('limit')) || 60))
  const statuses = searchParams.getAll('status')
  const tags = searchParams.getAll('tag')
  const dateFrom = searchParams.get('dateFrom')
  const dateTo = searchParams.get('dateTo')

  const all = readInboxImages()
  const availableTags = [...new Set(all.flatMap((i) => i.tags))].sort()

  let filtered = all
  if (statuses.length > 0) {
    filtered = filtered.filter((i) => {
      if (statuses.includes('paused') && i.isPaused) return true
      if (statuses.includes('stuck') && i.isStuck) return true
      if (statuses.includes('done') && i.isDone) return true
      if (statuses.includes('pending') && !i.isPaused && !i.isStuck && !i.isDone) return true
      return false
    })
  }
  if (tags.length > 0) {
    filtered = filtered.filter((i) => tags.some((t) => i.tags.includes(t)))
  }
  if (dateFrom) {
    const from = new Date(dateFrom).getTime()
    filtered = filtered.filter((i) => new Date(i.ingestedAt).getTime() >= from)
  }
  if (dateTo) {
    const to = new Date(dateTo).getTime() + 24 * 60 * 60 * 1000
    filtered = filtered.filter((i) => new Date(i.ingestedAt).getTime() < to)
  }

  let stuck = 0
  let withToken = 0
  for (const item of filtered) {
    if (item.isStuck) stuck++
    if (item.hasToken) withToken++
  }

  const page: InboxPage = {
    total: filtered.length,
    stuck,
    withToken,
    availableTags,
    items: filtered.slice(offset, offset + limit),
  }
  return NextResponse.json(page)
}
