'use client'

import { useState, useEffect, useCallback } from 'react'
import type { ReviewItem } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import ReviewCard from '@/components/gm/ReviewCard'
import { CheckSquare, Loader2 } from 'lucide-react'

interface Toast {
  message: string
  type: 'success' | 'error'
}

export default function GMReviewPage() {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState<Toast | null>(null)
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sortBy, setSortBy] = useState('created')

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const fetchItems = useCallback(async () => {
    try {
      const res = await fetch('/api/review')
      if (!res.ok) throw new Error('fetch failed')
      const data: ReviewItem[] = await res.json()
      setItems(data)
    } catch {
      showToast('Failed to load review items', 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchItems()
  }, [fetchItems])

  const handleApprove = async (filename: string) => {
    try {
      const res = await fetch('/api/gm/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      const data = await res.json()
      if (data.ok) {
        showToast('Approved and promoted to Library', 'success')
        fetchItems()
      } else {
        showToast(data.error ?? 'Approve failed', 'error')
      }
    } catch {
      showToast('Approve failed', 'error')
    }
  }

  const handleReject = async (filename: string) => {
    try {
      const res = await fetch('/api/gm/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      const data = await res.json()
      if (data.ok) {
        showToast('Draft rejected', 'success')
        fetchItems()
      } else {
        showToast(data.error ?? 'Reject failed', 'error')
      }
    } catch {
      showToast('Reject failed', 'error')
    }
  }

  const handleReprocess = async (filename: string) => {
    try {
      const res = await fetch('/api/gm/flag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      const data = await res.json()
      if (data.ok) {
        showToast('Queued for reprocessing', 'success')
        fetchItems()
      } else {
        showToast(data.error ?? 'Reprocess failed', 'error')
      }
    } catch {
      showToast('Reprocess failed', 'error')
    }
  }

  const allTypes = Array.from(new Set(items.map((i) => i.type))).filter(Boolean).sort()
  const allStatuses = Array.from(new Set(items.map((i) => i.status))).filter(Boolean).sort()

  const filtered = items
    .filter((i) => typeFilter === 'all' || i.type === typeFilter)
    .filter((i) => statusFilter === 'all' || i.status === statusFilter)
    .sort((a, b) => {
      if (sortBy === 'created') return (b.created ?? '').localeCompare(a.created ?? '')
      if (sortBy === 'name') return a.id.localeCompare(b.id)
      return 0
    })

  const unreviewed = items.filter((i) => !i.reviewed).length
  const approved = items.filter((i) => i.status === 'approved').length

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={CheckSquare}
        title="Review Queue"
        subtitle={`${items.length} drafts · ${unreviewed} unreviewed`}
      />

      {/* KPIs */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Pending</div>
          <div className="text-3xl font-mono font-semibold text-warning">{unreviewed}</div>
          <div className="text-xs text-zinc-500 mt-1">unreviewed</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Approved</div>
          <div className="text-3xl font-mono font-semibold text-primary">{approved}</div>
          <div className="text-xs text-zinc-500 mt-1">in queue</div>
        </div>
        <div className="panel p-4">
          <div className="text-xs text-zinc-500 mb-1 uppercase tracking-wide">Total</div>
          <div className="text-3xl font-mono font-semibold text-zinc-300">{items.length}</div>
          <div className="text-xs text-zinc-500 mt-1">drafts</div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="panel p-3 mb-4 flex flex-wrap gap-2 items-center">
        <span className="text-xs text-zinc-500 uppercase tracking-wide font-semibold">
          Filter:
        </span>

        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors"
        >
          <option value="all">All Types</option>
          {allTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors"
        >
          <option value="all">All Statuses</option>
          {allStatuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-zinc-500">Sort:</span>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 px-2 py-1.5 rounded outline-none focus:border-primary/40 transition-colors"
          >
            <option value="created">Created</option>
            <option value="name">Name</option>
          </select>
        </div>

        <span className="text-xs text-zinc-600">
          {filtered.length} / {items.length}
        </span>
      </div>

      {/* Content */}
      {loading ? (
        <div className="panel p-12 text-center">
          <Loader2 size={20} className="mx-auto text-zinc-600 mb-2 animate-spin" />
          <div className="text-zinc-500 text-sm">Loading drafts...</div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="panel p-12 text-center">
          <CheckSquare size={24} className="mx-auto text-zinc-600 mb-3" />
          <div className="text-zinc-500 text-sm">
            {items.length === 0
              ? 'No drafts in 01-Processing'
              : 'No items match the current filters'}
          </div>
          <div className="text-xs text-zinc-600 mt-1">
            {items.length === 0
              ? 'Files appear here after agents process inbox items'
              : 'Try clearing the filters'}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {filtered.map((item) => (
            <ReviewCard
              key={item.filename}
              item={item}
              onApprove={handleApprove}
              onReject={handleReject}
              onReprocess={handleReprocess}
            />
          ))}
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-lg text-sm font-medium z-50 shadow-lg ${
            toast.type === 'success'
              ? 'bg-success text-white'
              : 'bg-danger text-white'
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  )
}
