import type { TokenFile } from '@/lib/types'

interface TokenCardProps {
  token: TokenFile
}

export default function TokenCard({ token }: TokenCardProps) {
  const src = `/api/image?path=${encodeURIComponent(token.path)}`

  return (
    <div className="panel p-3 flex flex-col items-center gap-2">
      <div className="w-24 h-24 rounded-full overflow-hidden bg-surface-3 border border-surface-3 flex-shrink-0">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={token.entityId ?? token.filename}
          className="w-full h-full object-cover"
          onError={(e) => {
            const target = e.target as HTMLImageElement
            target.style.display = 'none'
          }}
        />
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
