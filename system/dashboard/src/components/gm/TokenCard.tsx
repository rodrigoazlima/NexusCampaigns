import type { TokenFile } from '@/lib/types'
import VaultImage from '@/components/shared/VaultImage'

interface TokenCardProps {
  token: TokenFile
}

export default function TokenCard({ token }: TokenCardProps) {
  return (
    <div className="panel p-3 flex flex-col items-center gap-2">
      <div className="w-24 h-24 rounded-full overflow-hidden bg-surface-3 border border-surface-3 flex-shrink-0">
        <VaultImage path={token.path} className="w-full h-full object-cover" alt={token.entityId ?? token.filename} />
      </div>
      <div
        className="text-xs font-mono text-zinc-300 text-center truncate w-full"
        title={token.entityId ?? token.filename}
      >
        {token.entityId ?? token.filename}
      </div>
    </div>
  )
}
