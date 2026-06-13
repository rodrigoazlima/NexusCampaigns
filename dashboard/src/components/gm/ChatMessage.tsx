import type { GMChatMessage } from '@/lib/types'
import { formatRelative } from '@/lib/utils'

interface ChatMessageProps {
  msg: GMChatMessage
}

function renderContent(content: string) {
  // Split on code blocks and render them
  const parts = content.split(/(```[\s\S]*?```)/g)
  return parts.map((part, i) => {
    if (part.startsWith('```')) {
      const lines = part.split('\n')
      const lang = lines[0].replace('```', '').trim()
      const code = lines.slice(1, -1).join('\n')
      return (
        <pre key={i} className="bg-black/40 rounded p-2 text-xs font-mono overflow-x-auto my-1 text-zinc-300">
          {lang && <span className="text-zinc-600 text-[10px] block mb-1">{lang}</span>}
          {code}
        </pre>
      )
    }
    return (
      <span key={i} className="whitespace-pre-wrap">{part}</span>
    )
  })
}

export default function ChatMessage({ msg }: ChatMessageProps) {
  const isUser = msg.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%]">
          <div className="bg-primary/20 text-zinc-200 text-xs px-3 py-2 rounded-lg rounded-tr-sm">
            {msg.content}
          </div>
          <div className="text-[10px] text-zinc-600 text-right mt-1">
            {formatRelative(msg.timestamp)}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        <div className="flex items-center gap-1.5 mb-1">
          <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-wide">
            {msg.agent}
          </span>
        </div>
        <div className="bg-surface-1 border border-surface-3 text-zinc-300 text-xs px-3 py-2 rounded-lg rounded-tl-sm">
          {renderContent(msg.content)}
        </div>
        <div className="text-[10px] text-zinc-600 mt-1">
          {formatRelative(msg.timestamp)}
        </div>
      </div>
    </div>
  )
}
