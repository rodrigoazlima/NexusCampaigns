'use client'

import { useState, useEffect } from 'react'
import type { InboxImage } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import InboxImageCard from '@/components/gm/InboxImageCard'
import { Image, Loader2, AlertTriangle } from 'lucide-react'

export default function GMInboxPage() {
  const [items, setItems] = useState<InboxImage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/gm/inbox')
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load')
        return r.json()
      })
      .then((data: InboxImage[]) => {
        setItems(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(String(err))
        setLoading(false)
      })
  }, [])

  const stuck = items.filter((i) => i.isStuck)
  const withToken = items.filter((i) => i.hasToken)

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={Image}
        title="Inbox Gallery"
        subtitle={`${items.length} images in queue`}
      />

      {/* Stats strip */}
      {!loading && items.length > 0 && (
        <div className="flex flex-wrap gap-3 mb-6">
          <div className="panel px-4 py-3 flex items-center gap-2">
            <span className="text-2xl font-mono font-bold text-zinc-200">{items.length}</span>
            <span className="text-xs text-zinc-500">total images</span>
          </div>
          <div className="panel px-4 py-3 flex items-center gap-2">
            <span className={`text-2xl font-mono font-bold ${stuck.length > 0 ? 'text-danger' : 'text-success'}`}>
              {stuck.length}
            </span>
            <span className="text-xs text-zinc-500">stuck (&gt;24h)</span>
          </div>
          <div className="panel px-4 py-3 flex items-center gap-2">
            <span className="text-2xl font-mono font-bold text-success">{withToken.length}</span>
            <span className="text-xs text-zinc-500">with token</span>
          </div>
        </div>
      )}

      {/* Stuck warning */}
      {!loading && stuck.length > 0 && (
        <div className="mb-4 p-3 rounded-lg border border-danger/30 bg-danger/5 flex items-center gap-2 text-sm">
          <AlertTriangle size={15} className="text-danger flex-shrink-0" />
          <span className="text-danger font-medium">{stuck.length} items</span>
          <span className="text-zinc-400">have been in the queue for over 24 hours without completing</span>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="panel p-12 text-center">
          <Loader2 size={20} className="mx-auto text-zinc-600 mb-2 animate-spin" />
          <div className="text-zinc-500 text-sm">Loading inbox images...</div>
        </div>
      ) : error ? (
        <div className="panel p-12 text-center">
          <div className="text-danger text-sm">{error}</div>
        </div>
      ) : items.length === 0 ? (
        <div className="panel p-12 text-center">
          {/* eslint-disable-next-line jsx-a11y/alt-text */}
          <Image size={28} className="mx-auto text-zinc-600 mb-3" />
          <div className="text-zinc-500 text-sm">No images in inbox queue</div>
          <div className="text-xs text-zinc-600 mt-1">
            Drop images into 00-Inbox/ to get started
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {items.map((item) => (
            <InboxImageCard key={item.path} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
