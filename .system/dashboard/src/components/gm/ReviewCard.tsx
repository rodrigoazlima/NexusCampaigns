'use client'

import { useState } from 'react'
import Link from 'next/link'
import type { ReviewItem } from '@/lib/types'
import QualityBar from '@/components/widgets/QualityBar'
import GMActionBar from './GMActionBar'
import ImageModal from './ImageModal'
import { ExternalLink } from 'lucide-react'

const TYPE_COLORS: Record<string, string> = {
  npc: 'bg-blue-500/10 text-blue-400',
  character: 'bg-blue-500/10 text-blue-400',
  location: 'bg-green-500/10 text-green-400',
  faction: 'bg-purple-500/10 text-purple-400',
  quest: 'bg-yellow-500/10 text-yellow-400',
  creature: 'bg-red-500/10 text-red-400',
  item: 'bg-orange-500/10 text-orange-400',
  lore: 'bg-teal-500/10 text-teal-400',
}

interface ReviewCardProps {
  item: ReviewItem
  onApprove: (filename: string, quality: number) => Promise<void>
  onReject: (filename: string) => Promise<void>
  onReprocess: (filename: string) => Promise<void>
}

export default function ReviewCard({ item, onApprove, onReject, onReprocess }: ReviewCardProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string }[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [loading, setLoading] = useState(false)

  const imageSrc = item.source[0]
    ? `/api/image?path=${encodeURIComponent(item.source[0])}`
    : null

  const handleApprove = async (q: number) => {
    setLoading(true)
    await onApprove(item.filename, q)
    setLoading(false)
  }

  const handleReject = async () => {
    setLoading(true)
    await onReject(item.filename)
    setLoading(false)
  }

  const handleReprocess = async () => {
    setLoading(true)
    await onReprocess(item.filename)
    setLoading(false)
  }

  const handleSendChat = async () => {
    if (!chatInput.trim() || chatLoading) return
    const message = chatInput.trim()
    setChatInput('')
    setChatMessages((prev) => [...prev, { role: 'user', content: message }])
    setChatLoading(true)
    try {
      const res = await fetch('/api/gm/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          agent: 'lore',
          context: item.excerpt || item.id,
        }),
      })
      const data = await res.json()
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.content || data.error || 'No response' },
      ])
    } catch {
      setChatMessages((prev) => [...prev, { role: 'assistant', content: 'Failed to reach agent.' }])
    } finally {
      setChatLoading(false)
    }
  }

  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-col md:flex-row">
        {/* Left: image column */}
        <div className="md:w-44 flex-shrink-0 p-3 flex flex-col gap-2 border-b md:border-b-0 md:border-r border-surface-3">
          {imageSrc ? (
            <button
              className="w-full aspect-square overflow-hidden rounded-md bg-surface-3 border border-surface-3 hover:border-primary/40 transition-colors cursor-zoom-in"
              onClick={() => setModalOpen(true)}
              title="Click to enlarge"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imageSrc}
                alt={item.id}
                className="w-full h-full object-cover"
                onError={(e) => {
                  const t = e.target as HTMLImageElement
                  t.parentElement!.innerHTML =
                    '<div class="w-full h-full flex items-center justify-center text-zinc-600 text-xs">No image</div>'
                }}
              />
            </button>
          ) : (
            <div className="w-full aspect-square rounded-md bg-surface-3 flex items-center justify-center text-zinc-600 text-xs">
              No image
            </div>
          )}
          <div className="text-[10px] text-zinc-600 font-mono text-center truncate" title={item.filename}>
            {item.filename}
          </div>
        </div>

        {/* Right: content column */}
        <div className="flex-1 min-w-0 p-4">
          {/* Header */}
          <div className="flex items-start gap-2 mb-2 flex-wrap">
            <Link
              href={`/gm/view/${encodeURIComponent(item.id)}`}
              className="font-mono text-sm text-zinc-100 font-semibold hover:text-primary transition-colors inline-flex items-center gap-1"
            >
              {item.id}
              <ExternalLink size={11} className="text-zinc-600" />
            </Link>
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${TYPE_COLORS[item.type] ?? 'bg-zinc-700 text-zinc-400'}`}>
              {item.type}
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase ${
              item.status === 'approved'
                ? 'bg-success/10 text-success'
                : item.status === 'rejected'
                ? 'bg-danger/10 text-danger'
                : 'bg-zinc-700 text-zinc-400'
            }`}>
              {item.status}
            </span>
            {item.reviewed && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-semibold uppercase">
                reviewed
              </span>
            )}
          </div>

          {/* Quality */}
          <div className="mb-3 max-w-xs">
            <QualityBar score={item.quality} />
          </div>

          {/* Excerpt */}
          {item.excerpt && (
            <p className="text-xs text-zinc-400 mb-3 line-clamp-3">{item.excerpt}</p>
          )}

          {/* Tags */}
          {item.tags.length > 0 && (
            <div className="flex gap-1 flex-wrap mb-3">
              {item.tags.slice(0, 8).map((tag) => (
                <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-3 text-zinc-500 font-mono">
                  #{tag}
                </span>
              ))}
            </div>
          )}

          {/* Actions */}
          <GMActionBar
            filename={item.filename}
            onApprove={handleApprove}
            onReject={handleReject}
            onReprocess={handleReprocess}
            onChat={() => setChatOpen(!chatOpen)}
            loading={loading}
          />
        </div>
      </div>

      {/* Inline chat panel */}
      {chatOpen && (
        <div className="border-t border-surface-3 p-4 bg-surface">
          <div className="text-xs font-semibold text-zinc-500 mb-2 uppercase tracking-wide">
            Lore Agent Chat
          </div>
          <div className="space-y-2 mb-3 max-h-40 overflow-y-auto">
            {chatMessages.length === 0 && (
              <div className="text-xs text-zinc-600 italic">
                Ask the lore agent about &ldquo;{item.id}&rdquo;...
              </div>
            )}
            {chatMessages.map((msg, i) => (
              <div
                key={i}
                className={`text-xs p-2 rounded ${
                  msg.role === 'user'
                    ? 'bg-primary/10 text-zinc-200 text-right ml-8'
                    : 'bg-surface-3 text-zinc-300 mr-8'
                }`}
              >
                {msg.content}
              </div>
            ))}
            {chatLoading && (
              <div className="text-xs text-zinc-600 italic">Thinking...</div>
            )}
          </div>
          <div className="flex gap-2">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSendChat()
                }
              }}
              placeholder="Ask about this draft..."
              className="flex-1 bg-surface-3 border border-surface-3 focus:border-primary/40 rounded px-3 py-1.5 text-xs text-zinc-200 placeholder-zinc-600 outline-none transition-colors"
            />
            <button
              onClick={handleSendChat}
              disabled={chatLoading || !chatInput.trim()}
              className="px-3 py-1.5 bg-primary hover:bg-primary/80 text-white text-xs rounded transition-colors disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>
      )}

      {/* Image modal */}
      {imageSrc && (
        <ImageModal
          src={imageSrc}
          alt={item.id}
          open={modalOpen}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  )
}
