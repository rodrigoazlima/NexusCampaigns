'use client'

import { useState } from 'react'
import QualityPicker from './QualityPicker'
import { CheckCircle, XCircle, RefreshCw, MessageSquare } from 'lucide-react'

interface GMActionBarProps {
  filename: string
  onApprove: (quality: number) => void
  onReject: () => void
  onReprocess: () => void
  onChat: () => void
  loading?: boolean
}

export default function GMActionBar({
  onApprove,
  onReject,
  onReprocess,
  onChat,
  loading,
}: GMActionBarProps) {
  const [showQuality, setShowQuality] = useState(false)
  const [quality, setQuality] = useState<number | null>(null)

  const handleApproveClick = () => {
    if (!showQuality) {
      setShowQuality(true)
      return
    }
    if (quality === null) return
    onApprove(quality)
    setShowQuality(false)
    setQuality(null)
  }

  const handleReject = () => {
    if (confirm('Reject this draft? It will be marked quality 1.')) {
      onReject()
    }
  }

  return (
    <div className="space-y-3">
      {showQuality && (
        <div className="p-3 bg-surface-3 rounded-lg border border-surface-3">
          <QualityPicker value={quality} onChange={setQuality} />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={handleApproveClick}
          disabled={loading || (showQuality && quality === null)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-success/10 text-success border border-success/30 hover:bg-success/20 transition-colors disabled:opacity-50"
        >
          <CheckCircle size={13} />
          {showQuality ? (quality !== null ? `Confirm (${quality})` : 'Pick score…') : 'Approve'}
        </button>

        {showQuality && (
          <button
            onClick={() => { setShowQuality(false); setQuality(null) }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-surface-3 text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            Cancel
          </button>
        )}

        <button
          onClick={handleReject}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-danger/10 text-danger border border-danger/30 hover:bg-danger/20 transition-colors disabled:opacity-50"
        >
          <XCircle size={13} />
          Reject
        </button>

        <button
          onClick={onReprocess}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 transition-colors disabled:opacity-50"
        >
          <RefreshCw size={13} />
          Re-process
        </button>

        <button
          onClick={onChat}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors"
        >
          <MessageSquare size={13} />
          Chat
        </button>
      </div>
    </div>
  )
}
