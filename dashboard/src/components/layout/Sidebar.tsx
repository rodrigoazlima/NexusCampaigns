'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const NAV = [
  {
    section: 'Overview',
    items: [
      { href: '/',          icon: '⬡',  label: 'Executive' },
      { href: '/pipeline',  icon: '⟶',  label: 'Pipeline' },
    ],
  },
  {
    section: 'Operations',
    items: [
      { href: '/monitoring', icon: '📡', label: 'Monitoring' },
      { href: '/agents',   icon: '🤖', label: 'Agents' },
      { href: '/queue',    icon: '📥', label: 'Queue' },
      { href: '/health',   icon: '💊', label: 'Health Status' },
      { href: '/errors',   icon: '⚡', label: 'Errors' },
    ],
  },
  {
    section: 'Content',
    items: [
      { href: '/review',   icon: '👁',  label: 'Review', badge: true },
      { href: '/library',  icon: '📚', label: 'Library' },
    ],
  },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="w-56 shrink-0 flex flex-col bg-surface-1 border-r border-surface-3 h-screen sticky top-0 overflow-y-auto">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-surface-3">
        <div className="flex items-center gap-2">
          <span className="text-xl">🐉</span>
          <div>
            <div className="text-sm font-semibold text-white leading-tight">Knowledge Factory</div>
            <div className="text-xs text-neutral">DM Operations</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-5">
        {NAV.map(group => (
          <div key={group.section}>
            <div className="section-title px-2 mb-1">{group.section}</div>
            <ul className="space-y-0.5">
              {group.items.map(item => {
                const active = pathname === item.href
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={cn(
                        'flex items-center gap-2.5 px-2 py-1.5 rounded text-sm transition-colors',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
                        active
                          ? 'bg-primary/20 text-white font-medium'
                          : 'text-zinc-400 hover:text-zinc-100 hover:bg-surface-2'
                      )}
                    >
                      <span className="text-base w-5 text-center">{item.icon}</span>
                      {item.label}
                      {'badge' in item && item.badge && !active && (
                        <span className="ml-auto w-2 h-2 rounded-full bg-warning animate-pulse" />
                      )}
                      {active && <span className="ml-auto w-1 h-4 rounded-full bg-primary" />}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-surface-3">
        <div className="flex items-center gap-2">
          <span className="dot-live" />
          <span className="text-xs text-neutral">Live · 30s refresh</span>
        </div>
      </div>
    </aside>
  )
}
