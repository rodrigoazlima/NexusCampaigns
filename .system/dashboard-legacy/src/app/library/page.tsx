import { PageHeader } from '@/components/widgets/PageHeader'
import { cn, typeIcon, relativeTime } from '@/lib/utils'
import path from 'path'
import { VAULT_ROOT, scanDirectory, countFiles } from '@/lib/vault'
import type { ReviewItem } from '@/lib/types'

export const dynamic = 'force-dynamic'

async function getLibraryData() {
  const libDir = path.join(VAULT_ROOT, '02-Library')
  const files  = scanDirectory(libDir)

  const byType: Record<string, number> = {}
  const byQuality: number[] = new Array(11).fill(0)
  let totalQ = 0, qCount = 0

  const recent: ReviewItem[] = []

  for (const { path: relPath, fm } of files) {
    const type = fm.type ?? 'unknown'
    byType[type] = (byType[type] ?? 0) + 1

    const q = fm.quality ?? 0
    byQuality[Math.min(q, 10)]++
    if (q > 0) { totalQ += q; qCount++ }

    recent.push({
      path: relPath,
      filename: path.basename(relPath, '.md'),
      id: fm.id ?? path.basename(relPath, '.md'),
      sha256: typeof fm.sha256 === 'string' ? fm.sha256 : null,
      type, status: (fm.status ?? 'approved') as 'approved',
      quality: q,
      suggestedQuality: null,
      tags: Array.isArray(fm.tags) ? fm.tags : [],
      source: Array.isArray(fm.source) ? fm.source : [],
      reviewed: fm.reviewed ?? true,
      relationships: Array.isArray(fm.relationships) ? fm.relationships : [],
      hasRelationships: (Array.isArray(fm.relationships) && fm.relationships.length > 0) || (fm.body ?? '').includes('[['),
      isOrphan: !((fm.body ?? '').includes('[[')) && !(Array.isArray(fm.relationships) && fm.relationships.length > 0),
      createdAt: fm.created ?? '',
      updatedAt: fm.updated ?? '',
      description: '',
      imageUrl: null,
      tokenUrl: null,
      agentNotes: {},
    })
  }

  recent.sort((a, b) => b.createdAt.localeCompare(a.createdAt))

  return {
    total: files.length,
    byType,
    avgQuality: qCount > 0 ? Math.round((totalQ / qCount) * 10) / 10 : 0,
    byQuality,
    recent: recent.slice(0, 20),
    orphanCount: recent.filter(r => r.isOrphan).length,
  }
}

export default async function LibraryPage() {
  const data = await getLibraryData()

  const typesSorted = Object.entries(data.byType).sort((a, b) => b[1] - a[1])
  const maxCount = Math.max(...Object.values(data.byType), 1)

  return (
    <div className="animate-slide_in">
      <PageHeader title="Library Analytics" icon="📚" subtitle="02-Library — approved canon knowledge base" />

      <div className="p-6 space-y-6">

        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="card p-4 text-center border-t-2 border-t-success/60">
            <div className="text-2xl font-semibold text-success tabular-nums">{data.total}</div>
            <div className="text-xs text-neutral mt-1">Total Entities</div>
          </div>
          <div className="card p-4 text-center">
            <div className="text-2xl font-semibold text-white tabular-nums">{typesSorted.length}</div>
            <div className="text-xs text-neutral mt-1">Entity Types</div>
          </div>
          <div className="card p-4 text-center">
            <div className={cn('text-2xl font-semibold tabular-nums', data.avgQuality >= 7 ? 'text-success' : data.avgQuality >= 4 ? 'text-warning' : 'text-neutral')}>
              {data.avgQuality || '—'}
            </div>
            <div className="text-xs text-neutral mt-1">Avg Quality</div>
          </div>
          <div className="card p-4 text-center">
            <div className={cn('text-2xl font-semibold tabular-nums', data.orphanCount > 0 ? 'text-danger' : 'text-success')}>
              {data.orphanCount}
            </div>
            <div className="text-xs text-neutral mt-1">Orphan Entities</div>
          </div>
        </div>

        {/* Type breakdown + Quality dist */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

          <div className="card p-4">
            <div className="section-title mb-4">By Entity Type</div>
            <div className="space-y-2">
              {typesSorted.map(([type, count]) => (
                <div key={type}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-zinc-300 flex items-center gap-1.5">
                      <span>{typeIcon(type)}</span>{type}
                    </span>
                    <span className="text-white font-medium tabular-nums">{count}</span>
                  </div>
                  <div className="h-1.5 bg-surface-3 rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full" style={{ width: `${(count / maxCount) * 100}%` }} />
                  </div>
                </div>
              ))}
              {typesSorted.length === 0 && <div className="text-neutral text-sm text-center py-4">No entities yet</div>}
            </div>
          </div>

          <div className="card p-4">
            <div className="section-title mb-4">Quality Distribution</div>
            <QualityHistogram buckets={data.byQuality} />
          </div>

        </div>

        {/* Recent additions */}
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="section-title">Recently Added</div>
          </div>
          {data.recent.length === 0 ? (
            <div className="px-4 py-8 text-center text-neutral text-sm">
              02-Library is empty — promote approved drafts from Review.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-3 text-left">
                  <Th>Entity</Th><Th>Type</Th><Th>Quality</Th><Th>Tags</Th><Th>Links</Th><Th>Created</Th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map(item => (
                  <tr key={item.path} className="table-row-hover border-b border-surface-3/50">
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <span>{typeIcon(item.type)}</span>
                        <span className="font-medium text-white truncate max-w-[200px]">{item.id}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-neutral">{item.type}</td>
                    <td className="px-4 py-2.5">
                      <QualityPip q={item.quality} />
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {item.tags.slice(0, 3).map(t => (
                          <span key={t} className="badge bg-surface-3 text-neutral-light border-surface-4 text-xs">{t}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-neutral tabular-nums">{item.relationships.length}</td>
                    <td className="px-4 py-2.5 text-neutral text-xs">{relativeTime(item.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

      </div>
    </div>
  )
}

function QualityHistogram({ buckets }: { buckets: number[] }) {
  const max = Math.max(...buckets, 1)
  const scores = [1,2,3,4,5,6,7,8,9,10]
  return (
    <div className="flex items-end gap-1.5 h-24">
      {scores.map(s => {
        const count = buckets[s] ?? 0
        const color = s >= 7 ? 'bg-success' : s >= 4 ? 'bg-warning' : 'bg-danger'
        return (
          <div key={s} className="flex-1 flex flex-col items-center gap-1">
            <div className="w-full flex flex-col justify-end" style={{ height: '72px' }}>
              <div
                className={cn('w-full rounded-t transition-all', color)}
                style={{ height: `${(count / max) * 100}%` }}
                title={`Score ${s}: ${count}`}
              />
            </div>
            <span className="text-xs text-neutral">{s}</span>
          </div>
        )
      })}
    </div>
  )
}

function QualityPip({ q }: { q: number }) {
  const color = q >= 7 ? 'text-success' : q >= 4 ? 'text-warning' : q > 0 ? 'text-danger' : 'text-neutral'
  return <span className={cn('font-medium tabular-nums text-sm', color)}>{q || '—'}</span>
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-xs font-medium text-neutral uppercase tracking-wide">{children}</th>
}
