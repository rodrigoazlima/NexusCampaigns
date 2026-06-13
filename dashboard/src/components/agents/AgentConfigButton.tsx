'use client'

import { useState } from 'react'
import { Settings } from 'lucide-react'
import AgentConfigDialog from './AgentConfigDialog'
import type { AgentInfo } from '@/lib/types'
import { agentDisplayName } from '@/lib/utils'

export function AgentConfigButton({ agent }: { agent: AgentInfo }) {
  const [open, setOpen] = useState(false)
  const disabled = agent.status === 'planned'

  return (
    <>
      <button
        onClick={() => !disabled && setOpen(true)}
        disabled={disabled}
        title={disabled ? 'No configuration available' : `Configure ${agentDisplayName(agent.name)}`}
        className="p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-surface-2 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        <Settings size={13} />
      </button>
      <AgentConfigDialog
        agentName={agent.name}
        agentDisplayName={agentDisplayName(agent.name)}
        open={open}
        onClose={() => setOpen(false)}
      />
    </>
  )
}
