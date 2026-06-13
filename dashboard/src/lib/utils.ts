import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { formatDistanceToNow, format, parseISO } from 'date-fns'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return 'never'
  try { return formatDistanceToNow(parseISO(iso), { addSuffix: true }) }
  catch { return '—' }
}

export function fmtDate(iso: string | null | undefined, fmt = 'MMM d, HH:mm'): string {
  if (!iso) return '—'
  try { return format(parseISO(iso), fmt) }
  catch { return iso }
}

export function nextRunTime(lastRun: string | null, intervalSec: number): string {
  if (!lastRun) return 'soon'
  try {
    const next = new Date(parseISO(lastRun).getTime() + intervalSec * 1000)
    if (next <= new Date()) return 'overdue'
    return formatDistanceToNow(next, { addSuffix: true })
  } catch { return '—' }
}

export function pct(n: number, total: number): string {
  if (!total) return '0%'
  return Math.round((n / total) * 100) + '%'
}

export function statusColor(status: string): string {
  switch (status) {
    case 'running': return 'text-primary'
    case 'idle':    return 'text-neutral'
    case 'error':   return 'text-danger'
    case 'offline': return 'text-neutral'
    case 'approved': return 'text-success'
    case 'draft':   return 'text-warning'
    case 'review':  return 'text-primary'
    default:        return 'text-neutral-light'
  }
}

export function statusBadge(status: string): string {
  switch (status) {
    case 'running': return 'bg-primary/20 text-primary border-primary/30'
    case 'idle':    return 'bg-surface-3 text-neutral-light border-surface-4'
    case 'error':   return 'bg-danger/20 text-danger border-danger/30'
    case 'offline': return 'bg-surface-3 text-neutral border-surface-4'
    case 'approved': return 'bg-success/20 text-success border-success/30'
    case 'draft':   return 'bg-warning/20 text-warning border-warning/30'
    case 'review':  return 'bg-primary/20 text-primary/90 border-primary/30'
    case 'done':    return 'bg-success/20 text-success border-success/30'
    case 'pending': return 'bg-warning/20 text-warning border-warning/30'
    case 'skip':    return 'bg-surface-3 text-neutral border-surface-4'
    default:        return 'bg-surface-3 text-neutral-light border-surface-4'
  }
}

export function typeIcon(type: string): string {
  const map: Record<string, string> = {
    npc: '🧙', character: '👤', faction: '⚔️', location: '🏰', city: '🌆',
    village: '🏘️', dungeon: '🗡️', item: '💎', artifact: '🔮', quest: '📜',
    encounter: '⚔️', creature: '🐉', monster: '👹', event: '⚡', religion: '✨',
    organization: '🏛️', timeline: '📅', lore: '📖',
    portrait: '🖼️', battlemap: '🗺️', scene: '🌄', token: '🎭',
  }
  return map[type] ?? '📄'
}
