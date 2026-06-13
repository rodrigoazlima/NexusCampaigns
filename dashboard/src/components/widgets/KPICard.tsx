import { cn } from '@/lib/utils'

interface KPICardProps {
  label: string
  value: string | number
  sub?: string
  icon?: string
  trend?: 'up' | 'down' | 'neutral'
  trendValue?: string
  accent?: 'primary' | 'success' | 'warning' | 'danger' | 'neutral'
  className?: string
}

const accentBorder: Record<string, string> = {
  primary: 'border-t-primary/60',
  success: 'border-t-success/60',
  warning: 'border-t-warning/60',
  danger:  'border-t-danger/60',
  neutral: 'border-t-surface-4',
}
const accentText: Record<string, string> = {
  primary: 'text-primary',
  success: 'text-success',
  warning: 'text-warning',
  danger:  'text-danger',
  neutral: 'text-neutral',
}

export function KPICard({ label, value, sub, icon, trend, trendValue, accent = 'neutral', className }: KPICardProps) {
  return (
    <div className={cn('card border-t-2 p-4 animate-slide_in', accentBorder[accent], className)}>
      <div className="flex items-start justify-between mb-2">
        <span className="text-xs text-neutral uppercase tracking-wider font-medium">{label}</span>
        {icon && <span className="text-lg">{icon}</span>}
      </div>
      <div className={cn('kpi-value', accentText[accent])}>{value}</div>
      <div className="mt-1.5 flex items-center gap-2">
        {sub && <span className="text-xs text-neutral">{sub}</span>}
        {trendValue && (
          <span className={cn('text-xs font-medium',
            trend === 'up' ? 'text-success' :
            trend === 'down' ? 'text-danger' : 'text-neutral'
          )}>
            {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'} {trendValue}
          </span>
        )}
      </div>
    </div>
  )
}
