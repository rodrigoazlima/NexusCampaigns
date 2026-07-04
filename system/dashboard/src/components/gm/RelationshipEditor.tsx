'use client'

import { useState } from 'react'
import { X, Plus } from 'lucide-react'

interface RelationshipEditorProps {
  relationships: string[]
  onChange: (rels: string[]) => void
  disabled?: boolean
}

function normalizeWikilink(raw: string): string {
  const trimmed = raw.trim()
  if (trimmed.startsWith('[[') && trimmed.endsWith(']]')) return trimmed
  return `[[${trimmed.replace(/^\[\[|\]\]$/g, '')}]]`
}

function displayLink(rel: string): string {
  return rel.replace(/^\[\[|\]\]$/g, '')
}

export default function RelationshipEditor({ relationships, onChange, disabled }: RelationshipEditorProps) {
  const [input, setInput] = useState('')

  const add = () => {
    const val = normalizeWikilink(input)
    const inner = displayLink(val)
    if (!inner || relationships.includes(val)) {
      setInput('')
      return
    }
    onChange([...relationships, val])
    setInput('')
  }

  const remove = (rel: string) => onChange(relationships.filter((r) => r !== rel))

  return (
    <div className="flex flex-wrap gap-1.5 items-center">
      {relationships.map((rel) => (
        <span
          key={rel}
          className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary font-mono"
        >
          {displayLink(rel)}
          {!disabled && (
            <button
              onClick={() => remove(rel)}
              className="text-primary/50 hover:text-danger transition-colors"
              title="Remove"
            >
              <X size={10} />
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <div className="flex items-center gap-1">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); add() }
              if (e.key === 'Escape') setInput('')
            }}
            placeholder="entity-slug…"
            className="text-[11px] bg-transparent border-b border-dashed border-zinc-700 focus:border-primary/60 text-zinc-400 placeholder-zinc-700 outline-none w-28 font-mono py-0.5"
          />
          <button
            onClick={add}
            disabled={!input.trim()}
            className="text-zinc-600 hover:text-primary disabled:opacity-30 transition-colors"
            title="Add relationship"
          >
            <Plus size={12} />
          </button>
        </div>
      )}
    </div>
  )
}
