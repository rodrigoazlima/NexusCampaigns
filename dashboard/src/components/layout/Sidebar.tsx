'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  GitBranch,
  Bot,
  Inbox,
  Zap,
  Eye,
  BookOpen,
  Menu,
  X,
  Dices,
  CheckSquare,
  Image,
  CircleDot,
  MessageSquare,
} from 'lucide-react'

const nav = [
  {
    group: 'GAME MASTER',
    items: [
      { href: '/gm', label: 'GM Hub', icon: Dices },
      { href: '/gm/review', label: 'Review', icon: CheckSquare },
      { href: '/gm/inbox', label: 'Inbox', icon: Image },
      { href: '/gm/tokens', label: 'Tokens', icon: CircleDot },
      { href: '/gm/chat', label: 'Agent Chat', icon: MessageSquare },
    ],
  },
  {
    group: 'OVERVIEW',
    items: [
      { href: '/', label: 'Executive', icon: LayoutDashboard },
      { href: '/pipeline', label: 'Pipeline', icon: GitBranch },
    ],
  },
  {
    group: 'OPERATIONS',
    items: [
      { href: '/agents', label: 'Agents', icon: Bot },
      { href: '/queue', label: 'Queue', icon: Inbox },
      { href: '/errors', label: 'Errors', icon: Zap },
    ],
  },
  {
    group: 'CONTENT',
    items: [
      { href: '/review', label: 'Review', icon: Eye },
      { href: '/library', label: 'Library', icon: BookOpen },
    ],
  },
]

function isActive(href: string, pathname: string): boolean {
  if (href === '/') return pathname === '/'
  if (href === '/gm') return pathname === '/gm'
  return pathname === href || pathname.startsWith(href + '/')
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname()
  return (
    <nav className="flex-1 px-2 py-4 overflow-y-auto">
      {nav.map((section) => (
        <div key={section.group} className="mb-5">
          <div className="px-2 mb-1 text-[10px] font-semibold tracking-widest text-zinc-500 uppercase">
            {section.group}
          </div>
          {section.items.map(({ href, label, icon: Icon }) => {
            const active = isActive(href, pathname)
            return (
              <Link
                key={href}
                href={href}
                onClick={onNavigate}
                className={`flex items-center gap-2.5 px-2 py-2.5 md:py-2 rounded-md text-sm transition-colors mb-0.5 ${
                  active
                    ? 'bg-primary/20 text-white font-medium'
                    : 'text-zinc-400 hover:text-zinc-100 hover:bg-surface-3'
                }`}
              >
                <Icon size={15} className={active ? 'text-primary' : 'text-zinc-500'} />
                {label}
              </Link>
            )
          })}
        </div>
      ))}
    </nav>
  )
}

const LiveIndicator = () => (
  <div className="px-4 py-3 border-t border-surface-3">
    <div className="flex items-center gap-2 text-xs text-zinc-500">
      <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
      Live · 30s refresh
    </div>
  </div>
)

const Logo = () => (
  <div className="flex items-center gap-2">
    <span className="text-lg">🐉</span>
    <div>
      <div className="text-sm font-semibold text-zinc-100 leading-tight">Knowledge</div>
      <div className="text-sm font-semibold text-zinc-100 leading-tight">Factory</div>
    </div>
  </div>
)

export default function Sidebar() {
  const [open, setOpen] = useState(false)
  const pathname = usePathname()

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setOpen(false) }, [pathname])

  // Prevent body scroll when drawer open
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  return (
    <>
      {/* Desktop sidebar — hidden below md */}
      <aside className="hidden md:flex w-56 flex-shrink-0 flex-col bg-surface-1 border-r border-surface-3 h-screen">
        <div className="px-4 py-5 border-b border-surface-3">
          <Logo />
        </div>
        <NavLinks />
        <LiveIndicator />
      </aside>

      {/* Mobile top bar — visible below md */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-30 h-14 bg-surface-1 border-b border-surface-3 flex items-center px-3 gap-3">
        <button
          onClick={() => setOpen(true)}
          className="p-2.5 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-surface-3 transition-colors"
          aria-label="Open navigation"
        >
          <Menu size={20} />
        </button>
        <span className="text-base">🐉</span>
        <span className="text-sm font-semibold text-zinc-100">Nexus Campaigns</span>
        <div className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500 pr-1">
          <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
          Live
        </div>
      </div>

      {/* Mobile drawer */}
      {open && (
        <div className="md:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Navigation">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />
          {/* Drawer */}
          <aside className="absolute top-0 left-0 bottom-0 w-64 bg-surface-1 border-r border-surface-3 flex flex-col z-50">
            <div className="h-14 px-4 border-b border-surface-3 flex items-center justify-between">
              <Logo />
              <button
                onClick={() => setOpen(false)}
                className="p-2 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-surface-3 transition-colors"
                aria-label="Close navigation"
              >
                <X size={18} />
              </button>
            </div>
            <NavLinks onNavigate={() => setOpen(false)} />
            <LiveIndicator />
          </aside>
        </div>
      )}
    </>
  )
}
