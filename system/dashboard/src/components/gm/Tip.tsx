'use client'

import type { ReactNode } from 'react'

type Side = 'top' | 'bottom' | 'left' | 'right'

const POS: Record<Side, string> = {
  top:    'bottom-full left-1/2 -translate-x-1/2 mb-2',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
  left:   'right-full top-1/2 -translate-y-1/2 mr-2',
  right:  'left-full top-1/2 -translate-y-1/2 ml-2',
}

export function Tip({
  label,
  children,
  side = 'top',
  shortcut,
}: {
  label: string
  children: ReactNode
  side?: Side
  shortcut?: string
}) {
  return (
    <div className="relative group/tip inline-flex">
      {children}
      <div
        className={`pointer-events-none absolute z-50 flex items-center gap-1.5 whitespace-nowrap px-2 py-1 rounded-md bg-zinc-900 border border-zinc-700 shadow-xl opacity-0 group-hover/tip:opacity-100 transition-opacity duration-150 ${POS[side]}`}
      >
        <span className="text-zinc-200 text-[11px]">{label}</span>
        {shortcut && (
          <kbd className="px-1 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-[10px] font-mono text-zinc-400 leading-tight">
            {shortcut}
          </kbd>
        )}
      </div>
    </div>
  )
}
