'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import type { GMChatMessage } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import ChatMessage from '@/components/gm/ChatMessage'
import { MessageSquare, Trash2, Save, Send } from 'lucide-react'

const AGENTS = ['lore', 'wiki', 'classification'] as const
type AgentKey = (typeof AGENTS)[number]

const AGENT_DESCRIPTIONS: Record<AgentKey, string> = {
  lore: 'Worldbuilding, narrative, backstory',
  wiki: 'Formatting, wiki markup, cross-links',
  classification: 'Entity type detection and tagging',
}

export default function GMChatPage() {
  const [selectedAgent, setSelectedAgent] = useState<AgentKey>('lore')
  const [messages, setMessages] = useState<GMChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [saveNext, setSaveNext] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const loadMessages = useCallback((agent: AgentKey) => {
    try {
      const stored = localStorage.getItem(`gm-chat-${agent}`)
      setMessages(stored ? (JSON.parse(stored) as GMChatMessage[]) : [])
    } catch {
      setMessages([])
    }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => {
    loadMessages(selectedAgent)
  }, [selectedAgent, loadMessages])

  useEffect(() => {
    if (messages.length === 0) return
    try {
      localStorage.setItem(`gm-chat-${selectedAgent}`, JSON.stringify(messages))
    } catch {
      // ignore storage errors
    }
  }, [messages, selectedAgent])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    const message = input.trim()
    setInput('')

    const userMsg: GMChatMessage = {
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
      agent: selectedAgent,
    }
    setMessages((prev) => [...prev, userMsg])
    setIsLoading(true)

    try {
      const res = await fetch('/api/gm/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, agent: selectedAgent, save: saveNext }),
      })
      const data = await res.json()

      if (data.error) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant' as const,
            content: `Error: ${data.error}`,
            timestamp: new Date().toISOString(),
            agent: selectedAgent,
          },
        ])
      } else {
        setMessages((prev) => [...prev, data as GMChatMessage])
      }

      if (saveNext) setSaveNext(false)
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant' as const,
          content: 'Failed to connect to agent.',
          timestamp: new Date().toISOString(),
          agent: selectedAgent,
        },
      ])
    } finally {
      setIsLoading(false)
      textareaRef.current?.focus()
    }
  }

  const handleClear = () => {
    setMessages([])
    try {
      localStorage.removeItem(`gm-chat-${selectedAgent}`)
    } catch {
      // ignore
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="p-4 md:p-6 flex flex-col" style={{ height: 'calc(100vh - 4rem)' }}>
      <PageHeader
        icon={MessageSquare}
        title="Agent Chat"
        subtitle="Chat directly with vault knowledge agents"
      />

      {/* Agent selector */}
      <div className="flex gap-2 mb-4 flex-wrap items-start">
        {AGENTS.map((agent) => (
          <button
            key={agent}
            onClick={() => setSelectedAgent(agent)}
            className={`flex flex-col px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectedAgent === agent
                ? 'bg-primary text-white'
                : 'bg-surface-2 text-zinc-400 hover:text-zinc-100 hover:bg-surface-3 border border-surface-3'
            }`}
          >
            <span className="capitalize">{agent}</span>
            <span className={`text-[10px] font-normal mt-0.5 ${selectedAgent === agent ? 'text-white/70' : 'text-zinc-600'}`}>
              {AGENT_DESCRIPTIONS[agent]}
            </span>
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2 self-center">
          <label className="flex items-center gap-1.5 text-xs text-zinc-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={saveNext}
              onChange={(e) => setSaveNext(e.target.checked)}
              className="rounded accent-primary"
            />
            <Save size={12} />
            Save response to Processing
          </label>
          <button
            onClick={handleClear}
            disabled={messages.length === 0}
            className="flex items-center gap-1 px-3 py-1.5 text-xs text-zinc-500 hover:text-danger hover:bg-danger/10 rounded transition-colors border border-surface-3 disabled:opacity-40"
          >
            <Trash2 size={12} />
            Clear
          </button>
        </div>
      </div>

      {/* Chat area */}
      <div className="panel flex-1 overflow-y-auto p-4 mb-4 min-h-0">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <MessageSquare size={28} className="text-zinc-700 mb-3" />
            <div className="text-zinc-500 text-sm">
              Start a conversation with the{' '}
              <span className="text-primary font-medium capitalize">{selectedAgent}</span> agent
            </div>
            <div className="text-xs text-zinc-600 mt-1 max-w-xs">
              Press Enter to send · Shift+Enter for new line
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((msg, i) => (
              <ChatMessage key={i} msg={msg} />
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-surface-1 border border-surface-3 text-zinc-500 text-xs px-3 py-2 rounded-lg">
                  <span className="inline-flex gap-1">
                    <span className="animate-bounce" style={{ animationDelay: '0ms' }}>•</span>
                    <span className="animate-bounce" style={{ animationDelay: '150ms' }}>•</span>
                    <span className="animate-bounce" style={{ animationDelay: '300ms' }}>•</span>
                  </span>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={`Ask the ${selectedAgent} agent… (Enter to send, Shift+Enter for newline)`}
          rows={2}
          className="flex-1 bg-surface-1 border border-surface-3 focus:border-primary/40 rounded-lg px-3 py-2.5 text-sm text-zinc-200 placeholder-zinc-600 outline-none transition-colors resize-none"
          disabled={isLoading}
        />
        <button
          onClick={handleSend}
          disabled={isLoading || !input.trim()}
          className="flex items-center gap-1.5 px-4 py-2 bg-primary hover:bg-primary/80 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed self-end"
        >
          <Send size={14} />
          Send
        </button>
      </div>
    </div>
  )
}
