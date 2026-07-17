'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import type { InboxImage } from '@/lib/types'
import { formatRelative } from '@/lib/utils'
import { AlertTriangle, Pause } from 'lucide-react'
import ImageModal from './ImageModal'
import VaultImage from '@/components/shared/VaultImage'

const AGENT_COLORS: Record<string, string> = {
  done: 'bg-success',
  skip: 'bg-zinc-600',
  pending: 'bg-warning animate-pulse',
  error: 'bg-danger',
  running: 'bg-primary animate-pulse',
}

interface InboxImageCardProps {
  item: InboxImage
}

export default function InboxImageCard({ item }: InboxImageCardProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const router = useRouter()

  return (
    <div
      className={`panel overflow-hidden ${item.isStuck ? 'border-danger/40' : ''} ${item.entityId ? 'cursor-pointer hover:border-primary/40' : ''}`}
      onClick={() => {
        if (item.entityId) router.push(`/gm/view/${encodeURIComponent(item.entityId)}`)
      }}
    >
      {/* Image thumbnail - shrink-wrapped to the image's own box (w-fit) so the
          Stuck/Token badges below anchor to the image corners, not empty column space.
          max-w-full + h-auto on the img: never upscaled past its source size. */}
      <button
        className="block w-fit max-w-full min-w-24 min-h-24 mx-auto overflow-hidden bg-surface-3 relative cursor-zoom-in"
        onClick={(e) => {
          e.stopPropagation()
          if (item.entityId) {
            router.push(`/gm/view/${encodeURIComponent(item.entityId)}`)
          } else {
            setModalOpen(true)
          }
        }}
        title="Click to enlarge"
      >
        <VaultImage
          path={item.path}
          thumb
          alt={item.filename}
          loading="lazy"
          decoding="async"
          className="block max-w-full h-auto"
        />
        {item.isStuck && (
          <div className="absolute top-2 right-2 flex items-center gap-1 bg-danger/90 text-white text-[10px] font-semibold px-1.5 py-0.5 rounded">
            <AlertTriangle size={10} />
            Stuck
          </div>
        )}
        {item.hasToken && (
          <div className="absolute bottom-2 right-2 bg-success/90 text-white text-[10px] font-semibold px-1.5 py-0.5 rounded">
            Token
          </div>
        )}
        {item.isPaused && (
          <div className="absolute bottom-2 left-2 flex items-center gap-1 bg-neutral/90 text-white text-[10px] font-semibold px-1.5 py-0.5 rounded">
            <Pause size={10} />
            Paused
          </div>
        )}
      </button>

      {/* Info */}
      <div className="p-3">
        <div className="text-xs font-mono text-zinc-200 truncate mb-1" title={item.filename}>
          {item.filename}
        </div>
        <div className="text-[10px] text-zinc-500 mb-2" suppressHydrationWarning>
          {formatRelative(item.ingestedAt)}
        </div>

        {/* Agent slots */}
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(item.agentSlots).map(([agent, status]) => (
            <div key={agent} className="flex items-center gap-1" title={`${agent}: ${status}`}>
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${AGENT_COLORS[status] ?? 'bg-neutral'}`} />
              <span className="text-[10px] text-zinc-600">{agent}</span>
            </div>
          ))}
        </div>
      </div>

      <ImageModal
        src={`/api/image?path=${encodeURIComponent(item.path)}`}
        alt={item.filename}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </div>
  )
}
