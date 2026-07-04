'use client'

import { CheckCircle, XCircle, RefreshCw, MessageSquare, FileEdit } from 'lucide-react'

interface GMActionBarProps {
  filename: string
  onApprove: () => void
  onReject: () => void
  onReprocess: () => void
  onChat: () => void
  onEdit: () => void
  loading?: boolean
}

export default function GMActionBar({
  onApprove,
  onReject,
  onReprocess,
  onChat,
  onEdit,
  loading,
}: GMActionBarProps) {
  const handleReject = () => {
    if (confirm('Reject this draft? It will be marked quality 1.')) {
      onReject()
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={onApprove}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-success/10 text-success border border-success/30 hover:bg-success/20 transition-colors disabled:opacity-50"
        >
          <CheckCircle size={13} />
          Approve
        </button>

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

        <button
          onClick={onEdit}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-zinc-700/40 text-zinc-300 border border-zinc-600/40 hover:bg-zinc-700/70 transition-colors"
        >
          <FileEdit size={13} />
          Edit
        </button>
      </div>
    </div>
  )
}
