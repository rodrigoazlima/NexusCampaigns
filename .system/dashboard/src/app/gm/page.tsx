export const dynamic = 'force-dynamic'

import { readReviewItems, readQueue } from '@/lib/vault'
import Link from 'next/link'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import KPICard from '@/components/widgets/KPICard'
import { Dices, CheckSquare, Image, CircleDot, MessageSquare } from 'lucide-react'

export default async function GMHubPage() {
  const [items, queue] = await Promise.all([
    Promise.resolve(readReviewItems()),
    Promise.resolve(readQueue()),
  ])

  const pending = items.filter((i) => !i.reviewed).length
  const highQuality = items.filter((i) => i.quality >= 7).length
  const approved = items.filter((i) => i.status === 'approved').length
  const inboxDepth = queue.total

  const actionCards = [
    {
      href: '/gm/review',
      icon: CheckSquare,
      label: 'Review Queue',
      count: pending,
      description: `${items.length} total drafts · ${pending} need review`,
      accent: 'text-warning',
      borderClass: 'border-warning/20 hover:border-warning/40',
    },
    {
      href: '/gm/inbox',
      icon: Image,
      label: 'Inbox Gallery',
      count: inboxDepth,
      description: `${queue.pending} pending · ${queue.stuck} stuck`,
      accent: 'text-primary',
      borderClass: 'border-primary/20 hover:border-primary/40',
    },
    {
      href: '/gm/tokens',
      icon: CircleDot,
      label: 'Tokens',
      count: null as number | null,
      description: 'Browse generated tokens and frame library',
      accent: 'text-purple-400',
      borderClass: 'border-purple-500/20 hover:border-purple-500/40',
    },
    {
      href: '/gm/chat',
      icon: MessageSquare,
      label: 'Agent Chat',
      count: null as number | null,
      description: 'lore, wiki, classification',
      accent: 'text-success',
      borderClass: 'border-success/20 hover:border-success/40',
    },
  ] as const

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Dices}
        title="Game Master Area"
        subtitle="Human-in-the-loop review and control center"
      />

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        <KPICard
          label="Pending Review"
          value={pending}
          sub="unreviewed drafts"
          accent="warning"
        />
        <KPICard
          label="High Quality"
          value={highQuality}
          sub="quality ≥ 7"
          accent="success"
        />
        <KPICard
          label="Approved"
          value={approved}
          sub="in processing"
          accent="primary"
        />
        <KPICard
          label="Inbox Depth"
          value={inboxDepth}
          sub={`${queue.stuck} stuck`}
          accent={queue.stuck > 0 ? 'danger' : 'neutral'}
        />
      </div>

      {/* Action cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
        {actionCards.map((card) => {
          const Icon = card.icon
          return (
            <Link
              key={card.href}
              href={card.href}
              className={`panel p-5 border ${card.borderClass} transition-colors hover:bg-surface-2 group block`}
            >
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-surface-3 border border-surface-3 flex items-center justify-center flex-shrink-0">
                  <Icon size={22} className={card.accent} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 mb-1">
                    <span className="text-base font-semibold text-zinc-100">
                      {card.label}
                    </span>
                    {card.count !== null && (
                      <span className={`text-2xl font-mono font-bold ${card.accent}`}>
                        {card.count}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-zinc-500">{card.description}</p>
                </div>
              </div>
            </Link>
          )
        })}
      </div>

    </div>
  )
}
