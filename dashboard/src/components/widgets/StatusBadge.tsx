import { statusDotClass } from '@/lib/utils'

interface StatusBadgeProps {
  status: string
  size?: 'sm' | 'md'
}

const labelMap: Record<string, string> = {
  running: 'Running',
  idle: 'Idle',
  error: 'Error',
  offline: 'Offline',
  planned: 'Planned',
}

export default function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const dotCls = statusDotClass(status)
  const textCls = size === 'sm' ? 'text-xs' : 'text-sm'
  return (
    <span className={`inline-flex items-center gap-1.5 ${textCls}`}>
      <span className={`dot ${dotCls}`} />
      <span className="text-zinc-400">{labelMap[status] ?? status}</span>
    </span>
  )
}
