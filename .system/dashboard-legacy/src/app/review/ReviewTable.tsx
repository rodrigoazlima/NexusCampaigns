'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import { cn, statusBadge, typeIcon, relativeTime } from '@/lib/utils'
import type { ReviewItem } from '@/lib/types'

type SortKey = 'id' | 'type' | 'status' | 'quality' | 'created'
type SortDir = 'asc' | 'desc'

interface Props {
  items: ReviewItem[]
}

function sortItems(items: ReviewItem[], key: SortKey, dir: SortDir): ReviewItem[] {
  return [...items].sort((a, b) => {
    let cmp = 0
    switch (key) {
      case 'id':      cmp = a.id.localeCompare(b.id); break
      case 'type':    cmp = a.type.localeCompare(b.type); break
      case 'status':  cmp = a.status.localeCompare(b.status); break
      case 'quality': cmp = ((a.quality || a.suggestedQuality || 0)) - ((b.quality || b.suggestedQuality || 0)); break
      case 'created': cmp = (a.createdAt ?? '').localeCompare(b.createdAt ?? ''); break
    }
    return dir === 'asc' ? cmp : -cmp
  })
}

export function ReviewTable({ items: initialItems }: Props) {
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  const sorted = useMemo(() => {
    if (!sortKey) return initialItems
    return sortItems(initialItems, sortKey, sortDir)
  }, [initialItems, sortKey, sortDir])

  const arrow = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-surface-3 text-left">
            <SortTh label={`Entity${arrow('id')}`}     onClick={() => handleSort('id')} active={sortKey === 'id'} />
            <SortTh label={`Type${arrow('type')}`}     onClick={() => handleSort('type')} active={sortKey === 'type'} />
            <SortTh label={`Status${arrow('status')}`} onClick={() => handleSort('status')} active={sortKey === 'status'} />
            <SortTh label={`Quality${arrow('quality')}`} onClick={() => handleSort('quality')} active={sortKey === 'quality'} />
            <Th>Tags</Th>
            <Th>Links</Th>
            <Th>Source</Th>
            <SortTh label={`Created${arrow('created')}`} onClick={() => handleSort('created')} active={sortKey === 'created'} />
            <Th>{''}</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((item, i) => (
            <ReviewRow key={item.path} item={item} index={i} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReviewRow({ item, index }: { item: ReviewItem; index: number }) {
  const [imgError, setImgError] = useState(false)
  const [tokenError, setTokenError] = useState(false)
  const showImg   = item.imageUrl   && !imgError
  const showToken = item.tokenUrl   && !tokenError

  return (
    <tr
      className={cn(
        'border-b border-surface-3/50 transition-all duration-200',
        'opacity-0 translate-y-1',
        !item.reviewed && 'bg-warning/5',
        item.isOrphan && 'bg-danger/5',
      )}
      style={{
        animation: `fadeRowIn 0.25s ease forwards`,
        animationDelay: `${Math.min(index * 18, 400)}ms`,
      }}
    >
      {/* Entity + thumbnail(s) */}
      <td className="px-3 py-2 max-w-xs">
        <div className="flex items-center gap-2">
          {/* Source thumbnail or type icon */}
          {showImg ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={item.imageUrl!}
              alt=""
              onError={() => setImgError(true)}
              className="w-8 h-8 rounded object-cover shrink-0 ring-1 ring-surface-4"
            />
          ) : (
            <span className="text-base w-8 text-center shrink-0">{typeIcon(item.type)}</span>
          )}
          {/* Token thumbnail overlay */}
          {showToken && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={item.tokenUrl!}
              alt=""
              onError={() => setTokenError(true)}
              className="-ml-4 w-8 h-8 object-contain shrink-0 drop-shadow"
              title="Token generated"
            />
          )}
          <div className="min-w-0">
            <div className="font-medium text-white truncate max-w-[180px]" title={item.id}>
              {item.id}
            </div>
            {item.description && (
              <div className="text-xs text-neutral truncate max-w-[180px]" title={item.description}>
                {item.description}
              </div>
            )}
          </div>
        </div>
      </td>

      <td className="px-4 py-2 text-neutral">{item.type}</td>

      <td className="px-4 py-2">
        <span className={cn('badge', statusBadge(item.status))}>{item.status}</span>
      </td>

      <td className="px-4 py-2">
        <QualityBar quality={item.quality} suggested={item.suggestedQuality} />
      </td>

      <td className="px-4 py-2">
        <div className="flex flex-wrap gap-1 max-w-[140px]">
          {item.tags.slice(0, 3).map(t => (
            <span key={t} className="badge bg-surface-3 text-neutral-light border-surface-4 text-xs">{t}</span>
          ))}
          {item.tags.length > 3 && <span className="text-xs text-neutral">+{item.tags.length - 3}</span>}
        </div>
      </td>

      <td className="px-4 py-2">
        {item.isOrphan ? (
          <span className="text-danger text-xs">⚠ orphan</span>
        ) : (
          <span className="text-neutral text-xs">{item.relationships.length}</span>
        )}
      </td>

      <td className="px-4 py-2 text-neutral text-xs truncate max-w-[100px]">
        {item.source[0] ?? '—'}
      </td>

      <td className="px-4 py-2 text-neutral text-xs">{relativeTime(item.createdAt)}</td>

      <td className="px-3 py-2">
        <Link
          href={`/review/${item.sha256 ?? encodeURIComponent(item.filename)}`}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors whitespace-nowrap"
        >
          Review →
        </Link>
      </td>
    </tr>
  )
}

function QualityBar({ quality, suggested }: { quality: number; suggested: number | null }) {
  const display = quality > 0 ? quality : (suggested ?? 0)
  const isPending = quality === 0
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-surface-3 rounded-full overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-300', display >= 7 ? 'bg-success' : display >= 4 ? 'bg-warning' : 'bg-danger')}
          style={{ width: `${(display / 10) * 100}%` }}
        />
      </div>
      <span className={cn('text-xs tabular-nums font-medium', isPending ? 'text-neutral' : 'text-white')}>
        {isPending ? `~${suggested ?? 0}` : display}
      </span>
    </div>
  )
}

function SortTh({ label, onClick, active }: { label: string; onClick: () => void; active: boolean }) {
  return (
    <th
      onClick={onClick}
      className={cn(
        'px-4 py-2 text-xs font-medium uppercase tracking-wide cursor-pointer select-none transition-colors',
        active ? 'text-primary' : 'text-neutral hover:text-zinc-300',
      )}
    >
      {label}
    </th>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-xs font-medium text-neutral uppercase tracking-wide">{children}</th>
}
