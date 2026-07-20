'use client'

import type { LogLine } from '@/lib/types'
import { severityColor } from '@/lib/utils'
import { useLogPolling, type LogPollingOptions } from '@/lib/useLogPolling'

interface ActivityFeedProps {
  logs: LogLine[]
  maxHeight?: string
  poll?: LogPollingOptions
}

const severityBadge = (s: string) => {
  switch (s) {
    case 'ERROR': return 'bg-danger/20 text-danger'
    case 'WARN': return 'bg-warning/20 text-warning'
    case 'DEBUG': return 'bg-neutral/20 text-neutral'
    default: return 'bg-zinc-700 text-zinc-400'
  }
}

export default function ActivityFeed({ logs: initialLogs, maxHeight = '320px', poll }: ActivityFeedProps) {
  const logs = useLogPolling(initialLogs, poll ?? {})

  if (logs.length === 0) {
    return (
      <div className="text-sm text-zinc-500 text-center py-8">No log entries</div>
    )
  }

  return (
    <div className="overflow-y-auto font-mono text-xs" style={{ maxHeight }}>
      {logs.map((line, i) => (
        <div
          key={i}
          className="flex gap-2 px-3 py-1.5 hover:bg-surface-2 border-b border-surface-3/50 items-start"
        >
          <span className="text-zinc-600 whitespace-nowrap flex-shrink-0">{line.timestamp.slice(11, 19)}</span>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase whitespace-nowrap flex-shrink-0 ${severityBadge(line.severity)}`}>
            {line.severity}
          </span>
          <span className="text-zinc-500 whitespace-nowrap flex-shrink-0 max-w-[100px] truncate" title={line.task}>
            [{line.task}]
          </span>
          <span className={`flex-1 min-w-0 break-words ${severityColor(line.severity)}`}>{line.message}</span>
        </div>
      ))}
    </div>
  )
}
