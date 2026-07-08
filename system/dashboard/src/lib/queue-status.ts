import type { QueueItem } from './types'

export function isPaused(item: QueueItem): boolean {
  return Object.values(item.agents).some((s) => s === 'paused')
}

export function isStuck(item: QueueItem): boolean {
  const cutoff = Date.now() - 24 * 60 * 60 * 1000
  const t = new Date(item.ingestedAt).getTime()
  return (
    !isNaN(t) &&
    t < cutoff &&
    Object.values(item.agents).some((s) => s === 'pending')
  )
}

export function isDone(item: QueueItem): boolean {
  return Object.values(item.agents).every((s) => s === 'done' || s === 'skip')
}
