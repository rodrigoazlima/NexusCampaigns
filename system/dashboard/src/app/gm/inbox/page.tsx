'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import Masonry from 'react-masonry-css'
import type { InboxImage, InboxPage } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import InboxImageCard from '@/components/gm/InboxImageCard'
import { Image, Loader2, AlertTriangle, Upload } from 'lucide-react'
import { uploadImage, enqueueImage, isImageFile } from '@/lib/upload-image'

const MASONRY_BREAKPOINTS = { default: 4, 1279: 3, 1023: 2, 639: 1 }
const PAGE_SIZE = 60

export default function GMInboxPage() {
  const [items, setItems] = useState<InboxImage[]>([])
  const [summary, setSummary] = useState<Pick<InboxPage, 'total' | 'stuck' | 'withToken'> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fetchingRef = useRef(false)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadPage = useCallback((offset: number) => {
    if (fetchingRef.current) return
    fetchingRef.current = true
    fetch(`/api/gm/inbox?offset=${offset}&limit=${PAGE_SIZE}`)
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load')
        return r.json()
      })
      .then((data: InboxPage) => {
        setSummary({ total: data.total, stuck: data.stuck, withToken: data.withToken })
        setItems((prev) => {
          if (offset === 0) return data.items
          const seen = new Set(prev.map((i) => i.path))
          return [...prev, ...data.items.filter((i) => !seen.has(i.path))]
        })
      })
      .catch((err) => setError(String(err)))
      .finally(() => {
        fetchingRef.current = false
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    loadPage(0)
  }, [loadPage])

  const handleFilesSelected = useCallback(async (fileList: FileList | null) => {
    const files = Array.from(fileList ?? []).filter(isImageFile)
    if (files.length === 0) return
    setUploading(true)
    await Promise.all(files.map(async (f) => {
      const result = await uploadImage({ file: f })
      if (result.ok && result.path) await enqueueImage(result.path)
    }))
    setUploading(false)
    loadPage(0)
  }, [loadPage])

  const hasMore = summary !== null && items.length < summary.total

  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !hasMore) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadPage(items.length)
      },
      { rootMargin: '600px' }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, items.length, loadPage])

  const total = summary?.total ?? 0
  const stuckCount = summary?.stuck ?? 0
  const withTokenCount = summary?.withToken ?? 0

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={Image}
        title="Inbox Gallery"
        subtitle={`${total} images in queue`}
        actions={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                handleFilesSelected(e.target.files)
                e.target.value = ''
              }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-colors disabled:opacity-50"
            >
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {uploading ? 'Uploading…' : 'Upload'}
            </button>
          </>
        }
      />

      {/* Stats strip */}
      {!loading && total > 0 && (
        <div className="flex flex-wrap gap-3 mb-6">
          <div className="panel px-4 py-3 flex items-center gap-2">
            <span className="text-2xl font-mono font-bold text-zinc-200">{total}</span>
            <span className="text-xs text-zinc-500">total images</span>
          </div>
          <div className="panel px-4 py-3 flex items-center gap-2">
            <span className={`text-2xl font-mono font-bold ${stuckCount > 0 ? 'text-danger' : 'text-success'}`}>
              {stuckCount}
            </span>
            <span className="text-xs text-zinc-500">stuck (&gt;24h)</span>
          </div>
          <div className="panel px-4 py-3 flex items-center gap-2">
            <span className="text-2xl font-mono font-bold text-success">{withTokenCount}</span>
            <span className="text-xs text-zinc-500">with token</span>
          </div>
        </div>
      )}

      {/* Stuck warning */}
      {!loading && stuckCount > 0 && (
        <div className="mb-4 p-3 rounded-lg border border-danger/30 bg-danger/5 flex items-center gap-2 text-sm">
          <AlertTriangle size={15} className="text-danger flex-shrink-0" />
          <span className="text-danger font-medium">{stuckCount} items</span>
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
      ) : total === 0 ? (
        <div className="panel p-12 text-center">
          {/* eslint-disable-next-line jsx-a11y/alt-text */}
          <Image size={28} className="mx-auto text-zinc-600 mb-3" />
          <div className="text-zinc-500 text-sm">No images in inbox queue</div>
          <div className="text-xs text-zinc-600 mt-1">
            Drop images into 00-Inbox/ to get started
          </div>
        </div>
      ) : (
        <>
          <Masonry
            breakpointCols={MASONRY_BREAKPOINTS}
            className="masonry-grid"
            columnClassName="masonry-grid_column"
          >
            {items.map((item) => (
              <InboxImageCard key={item.path} item={item} />
            ))}
          </Masonry>
          {hasMore && (
            <div ref={sentinelRef} className="p-6 text-center">
              <Loader2 size={16} className="mx-auto text-zinc-600 animate-spin" />
            </div>
          )}
        </>
      )}
    </div>
  )
}
