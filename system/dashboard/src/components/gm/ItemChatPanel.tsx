'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import type { ReviewItem, AgentInfo, GMChatMessage } from '@/lib/types'
import ChatMessage from './ChatMessage'
import { agentDisplayName } from '@/lib/utils'

interface ItemChatPanelProps {
  item: ReviewItem
  agents: AgentInfo[]
}

export default function ItemChatPanel({ item, agents }: ItemChatPanelProps) {
  const activeAgents = agents.filter((a) => a.status !== 'planned' && a.name !== 'runtime')
  const [collapsed, setCollapsed] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState(
    activeAgents.some((a) => a.name === 'lore') ? 'lore' : activeAgents[0]?.name ?? 'lore'
  )
  const [messages, setMessages] = useState<GMChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    if (!input.trim() || loading) return
    const message = input.trim()
    setInput('')
    const userMsg: GMChatMessage = {
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
      agent: selectedAgent,
    }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    const context = [
      `Entity: ${item.id}`,
      `Type: ${item.type}`,
      `Status: ${item.status}`,
      `Quality: ${item.quality}/10`,
      item.excerpt ? `Excerpt: ${item.excerpt}` : '',
      item.tags.length ? `Tags: ${item.tags.join(', ')}` : '',
    ].filter(Boolean).join('\n')

    try {
      const res = await fetch('/api/gm/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, agent: selectedAgent, context }),
      })
      const data = await res.json()
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: data.content ?? data.error ?? 'No response',
        timestamp: data.timestamp ?? new Date().toISOString(),
        agent: selectedAgent,
      }])
    } catch {
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: 'Failed to reach agent.',
        timestamp: new Date().toISOString(),
        agent: selectedAgent,
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="panel border-t border-surface-3">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-surface-3">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Chat</span>
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="text-xs bg-surface-3 border border-surface-3 text-zinc-300 rounded px-2 py-0.5 outline-none focus:border-primary/40"
          >
            {activeAgents.map((a) => (
              <option key={a.name} value={a.name}>
                {agentDisplayName(a.name)}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>

      {!collapsed && (
        <>
          {/* Messages */}
          <div
            className="p-4 space-y-2 overflow-y-auto"
            style={{ maxHeight: 'calc(100vh - var(--gm-header-height, 48px) - 160px)' }}
          >
            {messages.length === 0 && (
              <div className="text-xs text-zinc-600 italic">
                Ask {agentDisplayName(selectedAgent)} about &ldquo;{item.id}&rdquo;…
              </div>
            )}
            {messages.map((msg, i) => (
              <ChatMessage key={i} msg={msg} />
            ))}
            {loading && (
              <div className="flex items-center gap-2 text-xs text-zinc-600">
                <Loader2 size={12} className="animate-spin" />
                <span>{agentDisplayName(selectedAgent)} is thinking…</span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="px-4 pb-4 flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
              }}
              placeholder={`Ask ${agentDisplayName(selectedAgent)}…`}
              rows={2}
              className="flex-1 bg-surface-3 border border-surface-3 focus:border-primary/40 rounded px-3 py-2 text-xs text-zinc-200 placeholder-zinc-600 outline-none transition-colors resize-none"
            />
            <button
              onClick={send}
              disabled={loading || !input.trim()}
              className="px-3 bg-primary hover:bg-primary/80 text-white rounded transition-colors disabled:opacity-50 self-end py-2"
            >
              <Send size={14} />
            </button>
          </div>
        </>
      )}
    </div>
  )
}
