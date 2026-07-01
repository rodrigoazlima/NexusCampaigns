export const dynamic = 'force-dynamic'

import { readVaultStats, VAULT_ROOT } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import { BookOpen } from 'lucide-react'
import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'

interface LibraryEntity {
  filename: string
  id: string
  type: string
  status: string
  quality: number
  tags: string[]
  updated: string
  relationships: string[]
}

function readLibraryEntities(): LibraryEntity[] {
  const libDir = path.join(VAULT_ROOT, '02-Library')
  const entities: LibraryEntity[] = []
  try {
    const files = fs.readdirSync(libDir).filter((f) => f.endsWith('.md'))
    for (const file of files) {
      try {
        const raw = fs.readFileSync(path.join(libDir, file), 'utf-8')
        const { data } = matter(raw)
        entities.push({
          filename: file,
          id: data.id ?? file.replace('.md', ''),
          type: data.type ?? 'unknown',
          status: data.status ?? 'unknown',
          quality: typeof data.quality === 'number' ? data.quality : 0,
          tags: Array.isArray(data.tags) ? data.tags : [],
          updated: data.updated ?? '',
          relationships: Array.isArray(data.relationships) ? data.relationships : [],
        })
      } catch {
        // skip
      }
    }
  } catch {
    // dir missing
  }
  return entities.sort((a, b) => b.quality - a.quality)
}

export default async function LibraryPage() {
  const [stats, entities] = await Promise.all([
    Promise.resolve(readVaultStats()),
    Promise.resolve(readLibraryEntities()),
  ])

  // Type breakdown
  const byType: Record<string, number> = {}
  for (const e of entities) {
    byType[e.type] = (byType[e.type] ?? 0) + 1
  }

  // Quality histogram
  const histogram = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
  for (const e of entities) {
    const bucket = Math.min(9, Math.max(0, e.quality - 1))
    if (e.quality > 0) histogram[bucket]++
  }

  const qualityColor = (q: number) =>
    q >= 7 ? 'text-success' : q >= 4 ? 'text-warning' : 'text-danger'

  const qualityBg = (q: number) =>
    q >= 7 ? 'bg-success' : q >= 4 ? 'bg-warning' : 'bg-danger'

  const typeColors: Record<string, string> = {
    npc: 'bg-blue-500/10 text-blue-400',
    character: 'bg-blue-500/10 text-blue-400',
    location: 'bg-green-500/10 text-green-400',
    city: 'bg-green-500/10 text-green-400',
    village: 'bg-green-500/10 text-green-400',
    faction: 'bg-purple-500/10 text-purple-400',
    quest: 'bg-yellow-500/10 text-yellow-400',
    creature: 'bg-red-500/10 text-red-400',
    monster: 'bg-red-500/10 text-red-400',
    item: 'bg-orange-500/10 text-orange-400',
    artifact: 'bg-orange-500/10 text-orange-400',
    lore: 'bg-teal-500/10 text-teal-400',
    event: 'bg-pink-500/10 text-pink-400',
  }

  const maxHistCount = Math.max(...histogram, 1)

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={BookOpen}
        title="Library Analytics"
        subtitle={`${entities.length} approved entities in 02-Library`}
      />

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Total Entities</div>
          <div className="text-3xl font-mono font-semibold text-zinc-100">{entities.length}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">NPCs</div>
          <div className="text-3xl font-mono font-semibold text-blue-400">{stats.totalNpcs}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Library Files</div>
          <div className="text-3xl font-mono font-semibold text-success">{stats.library}</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Types</div>
          <div className="text-3xl font-mono font-semibold text-primary">{Object.keys(byType).length}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Type breakdown */}
        <div className="panel p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-4">By Type</div>
          {Object.entries(byType).length === 0 ? (
            <div className="text-sm text-zinc-500 text-center py-4">No entities in library</div>
          ) : (
            <div className="space-y-2">
              {Object.entries(byType)
                .sort(([, a], [, b]) => b - a)
                .map(([type, count]) => {
                  const pct = Math.round((count / entities.length) * 100)
                  return (
                    <div key={type} className="flex items-center gap-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-mono w-24 text-center ${
                        typeColors[type] ?? 'bg-zinc-700 text-zinc-400'
                      }`}>
                        {type}
                      </span>
                      <div className="flex-1 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary rounded-full"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-xs font-mono text-zinc-300 w-8 text-right">{count}</span>
                    </div>
                  )
                })}
            </div>
          )}
        </div>

        {/* Quality histogram */}
        <div className="panel p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 mb-4">Quality Distribution</div>
          <div className="flex items-end gap-1.5 h-32">
            {histogram.map((count, i) => {
              const score = i + 1
              const height = count === 0 ? 4 : Math.max(8, (count / maxHistCount) * 100)
              return (
                <div key={i} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[9px] font-mono text-zinc-600">{count > 0 ? count : ''}</span>
                  <div
                    className={`w-full rounded-sm ${qualityBg(score)} opacity-80`}
                    style={{ height: `${height}%` }}
                  />
                  <span className="text-[9px] font-mono text-zinc-500">{score}</span>
                </div>
              )
            })}
          </div>
          <div className="flex justify-between text-[10px] text-zinc-600 mt-2">
            <span>Reject</span>
            <span>Review</span>
            <span>Library</span>
          </div>
        </div>
      </div>

      {/* Entity table */}
      {entities.length > 0 && (
        <div className="panel overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="text-sm font-semibold text-zinc-200">Entities</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-3 text-zinc-500">
                  <th className="px-4 py-2 text-left">ID</th>
                  <th className="px-4 py-2 text-left">Type</th>
                  <th className="px-4 py-2 text-left">Quality</th>
                  <th className="px-4 py-2 text-left">Tags</th>
                  <th className="px-4 py-2 text-left">Links</th>
                  <th className="px-4 py-2 text-left">Updated</th>
                </tr>
              </thead>
              <tbody>
                {entities.map((e) => (
                  <tr key={e.filename} className="border-b border-surface-3/50 hover:bg-surface-2">
                    <td className="px-4 py-2 font-mono text-zinc-300">{e.id}</td>
                    <td className="px-4 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                        typeColors[e.type] ?? 'bg-zinc-700 text-zinc-400'
                      }`}>
                        {e.type}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`font-mono font-semibold ${qualityColor(e.quality)}`}>{e.quality}</span>
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex gap-1 flex-wrap">
                        {e.tags.slice(0, 3).map((tag) => (
                          <span key={tag} className="text-[10px] px-1 rounded bg-surface-3 text-zinc-500">
                            {tag}
                          </span>
                        ))}
                        {e.tags.length > 3 && <span className="text-[10px] text-zinc-600">+{e.tags.length - 3}</span>}
                      </div>
                    </td>
                    <td className="px-4 py-2 font-mono text-zinc-500">{e.relationships.length}</td>
                    <td className="px-4 py-2 text-zinc-500">{e.updated || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {entities.length === 0 && (
        <div className="panel p-12 text-center">
          <div className="text-zinc-500 text-sm">No entities in 02-Library yet</div>
          <div className="text-xs text-zinc-600 mt-2">Approve drafts from Review to populate the library</div>
        </div>
      )}
    </div>
  )
}
