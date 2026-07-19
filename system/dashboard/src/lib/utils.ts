import { formatDistanceToNow, format, parseISO } from 'date-fns'

export function formatRelative(dateStr: string | null): string {
  if (!dateStr) return 'never'
  try {
    const date = parseISO(dateStr)
    return formatDistanceToNow(date, { addSuffix: true })
  } catch {
    return 'unknown'
  }
}

export function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return '-'
  try {
    return format(parseISO(dateStr), 'MMM d, HH:mm:ss')
  } catch {
    return dateStr
  }
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${Math.round(ms / 1000)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

export function addSeconds(dateStr: string, seconds: number): string {
  try {
    const date = parseISO(dateStr)
    return new Date(date.getTime() + seconds * 1000).toISOString()
  } catch {
    return ''
  }
}

export function severityColor(severity: string): string {
  switch (severity) {
    case 'ERROR': return 'text-danger'
    case 'WARN': return 'text-warning'
    case 'DEBUG': return 'text-neutral'
    default: return 'text-zinc-300'
  }
}

export function severityBg(severity: string): string {
  switch (severity) {
    case 'ERROR': return 'bg-danger/10 text-danger border border-danger/20'
    case 'WARN': return 'bg-warning/10 text-warning border border-warning/20'
    case 'DEBUG': return 'bg-neutral/10 text-neutral border border-neutral/20'
    default: return 'bg-zinc-800 text-zinc-300 border border-zinc-700'
  }
}

export function qualityColor(score: number): string {
  if (score >= 7) return 'bg-success'
  if (score >= 4) return 'bg-warning'
  return 'bg-danger'
}

export function qualityLabel(score: number): string {
  if (score >= 9) return 'Excellent'
  if (score >= 7) return 'Good'
  if (score >= 4) return 'Review'
  return 'Reject'
}

export function statusDotClass(status: string): string {
  switch (status) {
    case 'running': return 'bg-success animate-pulse'
    case 'idle': return 'bg-success'
    case 'error': return 'bg-danger animate-pulse'
    case 'offline': return 'bg-neutral'
    case 'planned': return 'bg-zinc-600'
    default: return 'bg-neutral'
  }
}

export function agentDisplayName(id: string): string {
  return id
    .replace(/-agent$/, '')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}
