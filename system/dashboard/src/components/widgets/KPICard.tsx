interface KPICardProps {
  label: string
  value: string | number
  sub?: string
  accent?: 'primary' | 'success' | 'warning' | 'danger' | 'neutral'
  trend?: { value: number; label: string }
}

const accentMap = {
  primary: 'text-primary border-primary/30 bg-primary/5',
  success: 'text-success border-success/30 bg-success/5',
  warning: 'text-warning border-warning/30 bg-warning/5',
  danger: 'text-danger border-danger/30 bg-danger/5',
  neutral: 'text-neutral border-neutral/30 bg-neutral/5',
}

const valueColorMap = {
  primary: 'text-primary',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-zinc-300',
}

export default function KPICard({ label, value, sub, accent = 'neutral', trend }: KPICardProps) {
  return (
    <div className={`panel p-4 border ${accentMap[accent]}`}>
      <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2">{label}</div>
      <div className={`text-3xl font-semibold font-mono ${valueColorMap[accent]}`}>{value}</div>
      {sub && <div className="text-xs text-zinc-500 mt-1">{sub}</div>}
      {trend && (
        <div className={`text-xs mt-2 font-mono ${trend.value >= 0 ? 'text-success' : 'text-danger'}`}>
          {trend.value >= 0 ? '+' : ''}{trend.value} {trend.label}
        </div>
      )}
    </div>
  )
}
