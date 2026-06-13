'use client'

import { useState, useRef } from 'react'
import { X, Plus } from 'lucide-react'

interface TagEditorProps {
  tags: string[]
  onChange: (tags: string[]) => void
  disabled?: boolean
}

export default function TagEditor({ tags, onChange, disabled }: TagEditorProps) {
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const add = () => {
    const val = input.trim().toLowerCase().replace(/^#+/, '')
    if (!val || tags.includes(val)) {
      setInput('')
      return
    }
    onChange([...tags, val])
    setInput('')
  }

  const remove = (tag: string) => onChange(tags.filter((t) => t !== tag))

  return (
    <div className="flex flex-wrap gap-1.5 items-center">
      {tags.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-surface-3 text-zinc-400 font-mono"
        >
          #{tag}
          {!disabled && (
            <button
              onClick={() => remove(tag)}
              className="text-zinc-600 hover:text-danger transition-colors"
              title="Remove tag"
            >
              <X size={10} />
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <div className="flex items-center gap-1">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); add() }
              if (e.key === 'Escape') setInput('')
            }}
            placeholder="add tag…"
            className="text-[11px] bg-transparent border-b border-dashed border-zinc-700 focus:border-primary/60 text-zinc-400 placeholder-zinc-700 outline-none w-20 font-mono py-0.5"
          />
          <button
            onClick={add}
            disabled={!input.trim()}
            className="text-zinc-600 hover:text-primary disabled:opacity-30 transition-colors"
            title="Add tag"
          >
            <Plus size={12} />
          </button>
        </div>
      )}
    </div>
  )
}
