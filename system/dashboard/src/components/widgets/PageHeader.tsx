import type { LucideIcon } from 'lucide-react'

interface PageHeaderProps {
  icon?: LucideIcon
  title: string
  subtitle?: string
  actions?: React.ReactNode
}

export default function PageHeader({ icon: Icon, title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between flex-wrap gap-3 mb-6">
      <div className="flex items-center gap-3 min-w-0">
        {Icon && (
          <div className="w-9 h-9 shrink-0 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Icon size={18} className="text-primary" />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-zinc-100">{title}</h1>
          {subtitle && <p className="text-xs text-zinc-500 mt-0.5 break-words">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  )
}
