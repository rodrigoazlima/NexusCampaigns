'use client'

import { useEffect, useState } from 'react'
import type { LogLine } from '@/lib/types'

export interface LogPollingOptions {
  task?: string
  severity?: string
  limit?: number
  intervalMs?: number
}

// Generic client-side poller for /api/logs, shared by every log-displaying
// widget so each panel refreshes independently of the page-level AutoRefresh.
export function useLogPolling(initialLogs: LogLine[], opts: LogPollingOptions = {}): LogLine[] {
  const { task, severity, limit, intervalMs = 10000 } = opts
  const [logs, setLogs] = useState(initialLogs)

  useEffect(() => {
    const params = new URLSearchParams()
    if (task) params.set('task', task)
    if (severity) params.set('severity', severity)
    if (limit) params.set('limit', String(limit))

    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch(`/api/logs?${params.toString()}`, { cache: 'no-store' })
        if (!res.ok) return
        const data = (await res.json()) as LogLine[]
        if (!cancelled) setLogs(data)
      } catch {
        // network hiccup - keep showing last known logs
      }
    }

    const id = setInterval(poll, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [task, severity, limit, intervalMs])

  return logs
}
