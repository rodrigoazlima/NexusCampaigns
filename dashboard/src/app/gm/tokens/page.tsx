'use client'

import { useState, useEffect } from 'react'
import type { TokenFile } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import TokenCard from '@/components/gm/TokenCard'
import { CircleDot, Loader2 } from 'lucide-react'

interface TokensData {
  tokens: TokenFile[]
  frames: string[]
}

export default function GMTokensPage() {
  const [data, setData] = useState<TokensData>({ tokens: [], frames: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/gm/tokens')
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load')
        return r.json()
      })
      .then((d: TokensData) => {
        setData(d)
        setLoading(false)
      })
      .catch((err) => {
        setError(String(err))
        setLoading(false)
      })
  }, [])

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={CircleDot}
        title="Token Gallery"
        subtitle={`${data.tokens.length} generated tokens · ${data.frames.length} frames`}
      />

      {loading ? (
        <div className="panel p-12 text-center">
          <Loader2 size={20} className="mx-auto text-zinc-600 mb-2 animate-spin" />
          <div className="text-zinc-500 text-sm">Loading tokens...</div>
        </div>
      ) : error ? (
        <div className="panel p-12 text-center">
          <div className="text-danger text-sm">{error}</div>
        </div>
      ) : (
        <>
          {/* Generated tokens */}
          <div className="mb-8">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-sm font-semibold text-zinc-200">Generated Tokens</h2>
              <span className="text-xs text-zinc-500 bg-surface-3 px-2 py-0.5 rounded font-mono">
                {data.tokens.length}
              </span>
            </div>
            {data.tokens.length === 0 ? (
              <div className="panel p-8 text-center">
                <CircleDot size={22} className="mx-auto text-zinc-600 mb-2" />
                <div className="text-zinc-500 text-sm">No generated tokens found</div>
                <div className="text-xs text-zinc-600 mt-1">
                  Tokens appear here as *-token.png files in 00-Inbox/
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-3">
                {data.tokens.map((token) => (
                  <TokenCard key={token.path} token={token} />
                ))}
              </div>
            )}
          </div>

          {/* Token frames */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-sm font-semibold text-zinc-200">Token Frames</h2>
              <span className="text-xs text-zinc-500 bg-surface-3 px-2 py-0.5 rounded font-mono">
                {data.frames.length}
              </span>
            </div>
            {data.frames.length === 0 ? (
              <div className="panel p-8 text-center">
                <div className="text-zinc-500 text-sm">No frames found</div>
                <div className="text-xs text-zinc-600 mt-1">
                  Frames should be in 05-Assets/tokens/frames/
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10 gap-2">
                {data.frames.map((framePath) => {
                  const filename = framePath.split('/').pop() ?? framePath
                  return (
                    <div key={framePath} className="panel p-2 flex flex-col items-center gap-1">
                      <div className="w-16 h-16 overflow-hidden rounded-lg bg-surface-3">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={`/api/image?path=${encodeURIComponent(framePath)}`}
                          alt={filename}
                          className="w-full h-full object-contain"
                          onError={(e) => {
                            const t = e.target as HTMLImageElement
                            t.style.display = 'none'
                          }}
                        />
                      </div>
                      <div className="text-[9px] text-zinc-600 text-center truncate w-full font-mono" title={filename}>
                        {filename}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
