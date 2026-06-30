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
  FileText,
  Map,
  Users,
  Flag,
  ScrollText,
  Skull,
  Gem,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from 'lucide-react'

interface NavItem {
  href: string
  label: string
  icon: LucideIcon
}

interface NavSection {
  group: string
  items: NavItem[]
  collapsible?: boolean
  defaultOpen?: boolean
}

const nav: NavSection[] = [
  {
    group: 'GAME MASTER',
    collapsible: true,
    defaultOpen: true,
    items: [
      { href: '/gm/campaign', label: 'Campaign', icon: Dices },
      { href: '/gm/npcs', label: 'NPCs', icon: Users },
      { href: '/gm/quests', label: 'Quests', icon: ScrollText },
      { href: '/gm/places', label: 'Places', icon: Map },
      { href: '/gm/factions', label: 'Factions', icon: Flag },
      { href: '/gm/bestiary', label: 'Bestiary', icon: Skull },
      { href: '/gm/treasures', label: 'Treasures', icon: Gem },
      { href: '/gm/wiki', label: 'Wiki', icon: BookOpen },
    ],
  },
  {
    group: 'LEGACY',
    collapsible: true,
    defaultOpen: false,
    items: [
      { href: '/gm', label: 'GM Hub', icon: Dices },
      { href: '/gm/review', label: 'Review', icon: CheckSquare },
      { href: '/gm/inbox', label: 'Inbox', icon: Image },
      { href: '/gm/tokens', label: 'Tokens', icon: CircleDot },
      { href: '/gm/chat', label: 'Agent Chat', icon: MessageSquare },
      { href: '/', label: 'Executive', icon: LayoutDashboard },
      { href: '/pipeline', label: 'Pipeline', icon: GitBranch },
      { href: '/agents', label: 'Agents', icon: Bot },
      { href: '/prompt', label: 'Prompts', icon: FileText },
      { href: '/queue', label: 'Queue', icon: Inbox },
      { href: '/errors', label: 'Errors', icon: Zap },
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

function NavLink({ item, onNavigate, collapsed }: { item: NavItem; onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname()
  const { href, label, icon: Icon } = item
  const active = isActive(href, pathname)
  return (
    <Link
      href={href}
      onClick={onNavigate}
      title={collapsed ? label : undefined}
      className={`flex items-center gap-2.5 py-2.5 md:py-2 rounded-md text-sm transition-colors mb-0.5 ${
        collapsed ? 'justify-center px-0' : 'px-2'
      } ${
        active
          ? 'bg-primary/20 text-white font-medium'
          : 'text-zinc-400 hover:text-zinc-100 hover:bg-surface-3'
      }`}
    >
      <Icon size={15} className={active ? 'text-primary' : 'text-zinc-500'} />
      {!collapsed && label}
    </Link>
  )
}

function NavGroup({ section, onNavigate, collapsed, first }: { section: NavSection; onNavigate?: () => void; collapsed?: boolean; first?: boolean }) {
  const pathname = usePathname()
  const containsActive = section.items.some((i) => isActive(i.href, pathname))
  // Open by default, or whenever the group owns the active route (deep link).
  const [open, setOpen] = useState((section.defaultOpen ?? true) || containsActive)

  // Collapsed rail: no room for the group header — show a divider, render items
  // per their open state (a closed group stays hidden until the rail expands).
  if (collapsed) {
    return (
      <div className="mb-2">
        {!first && <div className="mx-2 my-2 border-t border-surface-3/60" />}
        {open && section.items.map((item) => (
          <NavLink key={item.href} item={item} onNavigate={onNavigate} collapsed />
        ))}
      </div>
    )
  }

  if (!section.collapsible) {
    return (
      <div className="mb-5">
        <div className="px-2 mb-1 text-[10px] font-semibold tracking-widest text-zinc-500 uppercase">
          {section.group}
        </div>
        {section.items.map((item) => (
          <NavLink key={item.href} item={item} onNavigate={onNavigate} />
        ))}
      </div>
    )
  }

  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1 px-2 mb-1 py-1 text-[10px] font-semibold tracking-widest text-zinc-500 hover:text-zinc-300 uppercase transition-colors"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {section.group}
      </button>
      {open &&
        section.items.map((item) => (
          <NavLink key={item.href} item={item} onNavigate={onNavigate} />
        ))}
    </div>
  )
}

function NavLinks({ onNavigate, collapsed }: { onNavigate?: () => void; collapsed?: boolean }) {
  return (
    <nav className="flex-1 px-2 py-4 overflow-y-auto">
      {nav.map((section, idx) => (
        <NavGroup key={section.group} section={section} onNavigate={onNavigate} collapsed={collapsed} first={idx === 0} />
      ))}
    </nav>
  )
}

const LiveIndicator = ({ collapsed }: { collapsed?: boolean }) => (
  <div className={`py-3 border-t border-surface-3 ${collapsed ? 'px-0 flex justify-center' : 'px-4'}`}>
    <span className="inline-block w-2 h-2 rounded-full bg-success animate-pulse" title="Live · 30s refresh" />
  </div>
)

const Logo = ({ collapsed }: { collapsed?: boolean }) => (
  <div className={`flex items-center gap-2 ${collapsed ? 'justify-center' : ''}`}>
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src="/logo-monogram.png" alt="Nexus Campaigns" className="w-9 h-9 shrink-0" />
    {!collapsed && (
      <div>
        <div className="text-sm font-semibold text-zinc-100 leading-tight">Nexus</div>
        <div className="text-sm font-semibold text-zinc-100 leading-tight">Campaigns</div>
      </div>
    )}
  </div>
)

const CollapseToggle = ({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) => (
  <button
    onClick={onToggle}
    title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
    aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
    className={`flex items-center gap-2.5 py-2.5 text-sm text-zinc-400 hover:text-zinc-100 hover:bg-surface-3 border-t border-surface-3 transition-colors ${
      collapsed ? 'justify-center px-0' : 'px-4'
    }`}
  >
    {collapsed ? <PanelLeftOpen size={16} /> : <><PanelLeftClose size={16} /> Collapse</>}
  </button>
)

export default function Sidebar() {
  const [open, setOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const pathname = usePathname()

  // Restore collapsed preference (desktop only).
  useEffect(() => {
    setCollapsed(localStorage.getItem('sidebar-collapsed') === '1')
  }, [])

  const toggleCollapsed = () => setCollapsed((v) => {
    const next = !v
    localStorage.setItem('sidebar-collapsed', next ? '1' : '0')
    return next
  })

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
      <aside className={`hidden md:flex flex-shrink-0 flex-col bg-surface-1 border-r border-surface-3 h-screen transition-all duration-200 ${collapsed ? 'w-14' : 'w-56'}`}>
        <div className={`py-5 border-b border-surface-3 ${collapsed ? 'px-0' : 'px-4'}`}>
          <Logo collapsed={collapsed} />
        </div>
        <NavLinks collapsed={collapsed} />
        <CollapseToggle collapsed={collapsed} onToggle={toggleCollapsed} />
        <LiveIndicator collapsed={collapsed} />
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
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo-mark.png" alt="" className="w-7 h-7" />
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
