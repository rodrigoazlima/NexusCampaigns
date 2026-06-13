export const dynamic = 'force-dynamic'

import { readReviewItems } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import QualityBar from '@/components/widgets/QualityBar'
import { Eye } from 'lucide-react'
import { formatDateTime } from '@/lib/utils'

export default async function ReviewPage() {
  const items = readReviewItems()

  const needsReview = items.filter((i) => !i.reviewed && i.quality >= 4)
  const highQuality = items.filter((i) => i.quality >= 7)
  const lowQuality = items.filter((i) => i.quality < 4 && i.quality > 0)

  const typeColors: Record<string, string> = {
    npc: 'bg-blue-500/10 text-blue-400',
    character: 'bg-blue-500/10 text-blue-400',
    location: 'bg-green-500/10 text-green-400',
    faction: 'bg-purple-500/10 text-purple-400',
    quest: 'bg-yellow-500/10 text-yellow-400',
    creature: 'bg-red-500/10 text-red-400',
    item: 'bg-orange-500/10 text-orange-400',
    lore: 'bg-teal-500/10 text-teal-400',
  }

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Eye}
        title="Human Review"
        subtitle={`${items.length} drafts in 01-Processing`}
      />

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Needs Review</div>
          <div className="text-3xl font-mono font-semibold text-warning">{needsReview.length}</div>
          <div className="text-xs text-zinc-500 mt-1">quality &ge; 4, not reviewed</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">High Quality</div>
          <div className="text-3xl font-mono font-semibold text-success">{highQuality.length}</div>
          <div className="text-xs text-zinc-500 mt-1">quality &ge; 7 (library-ready)</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Low Quality</div>
          <div className="text-3xl font-mono font-semibold text-danger">{lowQuality.length}</div>
          <div className="text-xs text-zinc-500 mt-1">quality &lt; 4 (reject)</div>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="panel p-12 text-center">
          <div className="text-zinc-500 text-sm">No drafts in 01-Processing</div>
          <div className="text-xs text-zinc-600 mt-2">Files will appear here after agents process inbox items</div>
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="text-sm font-semibold text-zinc-200">Drafts ({items.length})</div>
          </div>
          <div className="divide-y divide-surface-3">
            {items.map((item) => (
              <div key={item.filename} className="px-4 py-4 hover:bg-surface-2 transition-colors">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 sm:gap-4">
                  <div className="flex-1 min-w-0">
                    {/* Header row */}
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-mono text-sm text-zinc-200 font-medium">{item.id}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${
                        typeColors[item.type] ?? 'bg-zinc-700 text-zinc-400'
                      }`}>
                        {item.type}
                      </span>
                      {item.reviewed && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-success/10 text-success font-semibold uppercase">
                          reviewed
                        </span>
                      )}
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${
                        item.status === 'approved' ? 'bg-success/10 text-success' : 'bg-zinc-700 text-zinc-400'
                      }`}>
                        {item.status}
                      </span>
                    </div>

                    {/* Quality bar */}
                    <div className="max-w-xs mb-2">
                      <QualityBar score={item.quality} />
                    </div>

                    {/* Excerpt */}
                    {item.excerpt && (
                      <p className="text-xs text-zinc-500 line-clamp-2 mb-2">{item.excerpt}</p>
                    )}

                    {/* Tags */}
                    {item.tags.length > 0 && (
                      <div className="flex gap-1 flex-wrap">
                        {item.tags.slice(0, 6).map((tag) => (
                          <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-zinc-500 font-mono">
                            #{tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Meta */}
                  <div className="sm:flex-shrink-0 text-left sm:text-right text-xs text-zinc-600 space-y-1 sm:min-w-[120px]">
                    <div>{item.filename}</div>
                    {item.created && <div>Created {formatDateTime(item.created)}</div>}
                    {item.source.length > 0 && (
                      <div className="text-zinc-600">
                        {item.source.slice(0, 2).join(', ')}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
