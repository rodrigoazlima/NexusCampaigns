import type { QueueItem } from './types'

export type QueueStatus = 'error' | 'stuck' | 'pending' | 'paused' | 'done'

export const QUEUE_STATUSES: QueueStatus[] = ['error', 'stuck', 'pending', 'paused', 'done']

export const STATUS_META: Record<QueueStatus, { label: string; badge: string; chip: string }> = {
  error:   { label: 'Error',   badge: 'bg-danger/15 text-danger border-danger/40', chip: 'bg-danger/15 text-danger border-danger/40' },
  stuck:   { label: 'Stuck',   badge: 'bg-danger/15 text-danger border-danger/40', chip: 'bg-danger/15 text-danger border-danger/40' },
  pending: { label: 'Pending', badge: 'bg-warning/15 text-warning border-warning/40', chip: 'bg-warning/15 text-warning border-warning/40' },
  paused:  { label: 'Paused',  badge: 'bg-neutral/15 text-neutral border-neutral/40', chip: 'bg-neutral/15 text-neutral border-neutral/40' },
  done:    { label: 'Done',    badge: 'bg-success/15 text-success border-success/40', chip: 'bg-success/15 text-success border-success/40' },
}

type StatusInput = Pick<QueueItem, 'agents' | 'ingestedAt'>

// Single source of truth for a queue item's headline status. Priority matters:
// an item can have e.g. one 'error' slot and the rest 'done' - error wins so
// it doesn't silently read as pending.
export function resolveStatus(item: StatusInput): QueueStatus {
  const statuses = Object.values(item.agents)
  if (statuses.length > 0 && statuses.every((s) => s === 'done' || s === 'skip')) return 'done'
  if (statuses.some((s) => s === 'error')) return 'error'
  if (statuses.some((s) => s === 'paused')) return 'paused'
  if (statuses.some((s) => s === 'pending')) {
    const cutoff = Date.now() - 24 * 60 * 60 * 1000
    const t = new Date(item.ingestedAt).getTime()
    if (!isNaN(t) && t < cutoff) return 'stuck'
  }
  return 'pending'
}

export function canPause(item: StatusInput): boolean {
  return Object.values(item.agents).some((s) => s === 'pending')
}

export function canResume(item: StatusInput): boolean {
  return Object.values(item.agents).some((s) => s === 'paused')
}

export function canRetry(item: StatusInput): boolean {
  return Object.values(item.agents).some((s) => s === 'error')
}
