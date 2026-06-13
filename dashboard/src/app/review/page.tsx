import Link from 'next/link'
import { PageHeader } from '@/components/widgets/PageHeader'
import { cn } from '@/lib/utils'
import { getReviewItems } from '@/lib/vault'
import { AutoRefresh } from '@/components/AutoRefresh'
import { ReviewTable } from './ReviewTable'

export const dynamic = 'force-dynamic'

export default function ReviewPage() {
  const items = getReviewItems()

  const unreviewed = items.filter(i => !i.reviewed)
  const orphans    = items.filter(i => i.isOrphan)
  const highQ      = items.filter(i => (i.suggestedQuality ?? 0) >= 7)

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader
        title="Human Review"
        icon="👁"
        subtitle="01-Processing/ — approve, reject, score, promote to canon"
      />

      <div className="p-6 space-y-6">

        {/* Summary */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <SumCard label="Total Drafts"   value={items.length}      color="text-white" />
          <SumCard label="Needs Review"   value={unreviewed.length} color={unreviewed.length > 0 ? 'text-warning' : 'text-success'} />
          <SumCard label="High Quality"   value={highQ.length}      color="text-success" sub="score ≥ 7" />
          <SumCard label="Orphans"        value={orphans.length}    color={orphans.length > 0 ? 'text-danger' : 'text-neutral'} sub="no links" />
        </div>

        {/* Review queue */}
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              {unreviewed.length > 0 && <span className="dot-warn" />}
              <div className="section-title">Review Queue</div>
            </div>
            <span className="text-xs text-neutral">{unreviewed.length} unreviewed · {items.length} total · click headers to sort</span>
          </div>
          <ReviewTable items={items} />
        </div>

        {/* Promotion workflow */}
        <div className="card p-5">
          <div className="section-title mb-4">Promotion Workflow</div>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3 text-center">
            {[
              { step: '1', label: 'Find draft',    desc: 'Open in Obsidian via 01-Processing/', color: 'border-surface-4' },
              { step: '2', label: 'Review',         desc: 'Click Review → to open editor',       color: 'border-primary/40' },
              { step: '3', label: 'Set quality',   desc: 'Set quality ≥ 7 for library',          color: 'border-warning/40' },
              { step: '4', label: 'Mark reviewed', desc: 'Toggle reviewed + set status',          color: 'border-success/40' },
              { step: '5', label: 'Promote',        desc: 'Click ⬆ Promote → 02-Library/',       color: 'border-success/60' },
            ].map(s => (
              <div key={s.step} className={cn('card p-3 border-t-2', s.color)}>
                <div className="text-lg font-bold text-primary mb-1">{s.step}</div>
                <div className="text-sm font-medium text-white">{s.label}</div>
                <div className="text-xs text-neutral mt-1">{s.desc}</div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  )
}

function SumCard({ label, value, color, sub }: { label: string; value: number; color: string; sub?: string }) {
  return (
    <div className="card p-4 text-center">
      <div className={`text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
      <div className="text-sm text-white mt-0.5">{label}</div>
      {sub && <div className="text-xs text-neutral">{sub}</div>}
    </div>
  )
}
