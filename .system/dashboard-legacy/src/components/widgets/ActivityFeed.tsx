'use client'
import { cn, fmtDate } from '@/lib/utils'
import type { LogLine } from '@/lib/types'

interface ActivityFeedProps {
  logs: LogLine[]
  maxItems?: number
  className?: string
}

const severityStyle: Record<string, string> = {
  error:   'text-danger',
  warning: 'text-warning',
  info:    'text-zinc-400',
}

const severityIcon: Record<string, string> = {
  error:   '✗',
  warning: '⚠',
  info:    '·',
}

export function ActivityFeed({ logs, maxItems = 50, className }: ActivityFeedProps) {
  const items = logs.slice(0, maxItems)

  return (
    <div className={cn('font-mono text-xs overflow-auto max-h-96', className)}>
      {items.length === 0 && (
        <div className="text-neutral text-center py-8">No log entries</div>
      )}
      {items.map((log, i) => (
        <div
          key={i}
          className={cn(
            'flex gap-2 px-3 py-1 border-b border-surface-3/50 hover:bg-surface-2/40 transition-colors',
            log.severity !== 'info' && 'bg-surface-2/20'
          )}
        >
          <span className="text-neutral shrink-0 w-28">{fmtDate(log.timestamp)}</span>
          <span className="text-neutral/60 shrink-0 w-4 text-center">
            {severityIcon[log.severity]}
          </span>
          <span className="text-primary/80 shrink-0 w-36 truncate">[{log.taskId}]</span>
          <span className={cn('flex-1 truncate', severityStyle[log.severity])}>
            {log.message}
          </span>
        </div>
      ))}
    </div>
  )
}
