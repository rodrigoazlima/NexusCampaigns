'use client'

import { useState, useEffect } from 'react'
import type { TokenFile, TokenConfig } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import TokenCard from '@/components/gm/TokenCard'
import { CircleDot, Loader2, CheckCircle } from 'lucide-react'

interface TokensData {
  tokens: TokenFile[]
  frames: string[]
}

interface Toast { message: string; type: 'success' | 'error' }

export default function GMTokensPage() {
  const [data, setData] = useState<TokensData>({ tokens: [], frames: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [defaultMoldura, setDefaultMoldura] = useState<string>('')
  const [selectedMoldura, setSelectedMoldura] = useState<string>('')
  const [savingMoldura, setSavingMoldura] = useState(false)
  const [toast, setToast] = useState<Toast | null>(null)

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  useEffect(() => {
    Promise.all([
      fetch('/api/gm/tokens').then((r) => r.ok ? r.json() : Promise.reject('Failed to load tokens')),
      fetch('/api/gm/token/config').then((r) => r.ok ? r.json() : { molduraPath: '' }),
    ])
      .then(([tokensData, cfg]: [TokensData, TokenConfig]) => {
        setData(tokensData)
        setDefaultMoldura(cfg.molduraPath ?? '')
        setSelectedMoldura(cfg.molduraPath ?? '')
        setLoading(false)
      })
      .catch((err) => {
        setError(String(err))
        setLoading(false)
      })
  }, [])

  const handleSaveMoldura = async () => {
    if (!selectedMoldura) return
    setSavingMoldura(true)
    try {
      const res = await fetch('/api/gm/token/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ molduraPath: selectedMoldura }),
      })
      const data = await res.json()
      if (data.ok) {
        setDefaultMoldura(selectedMoldura)
        showToast('Default frame saved', 'success')
      } else {
        showToast(data.error ?? 'Save failed', 'error')
      }
    } catch (err) {
      showToast(String(err), 'error')
    } finally {
      setSavingMoldura(false)
    }
  }

  return (
    <div className="p-4 md:p-6">
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm font-medium shadow-lg ${
          toast.type === 'success' ? 'bg-success text-white' : 'bg-danger text-white'
        }`}>
          {toast.message}
        </div>
      )}

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
                  Tokens appear here as *-token.png files in 01-Processing/
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

          {/* Token frames + default selector */}
          <div>
            <div className="flex items-center justify-between gap-2 mb-4">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-zinc-200">Token Frames</h2>
                <span className="text-xs text-zinc-500 bg-surface-3 px-2 py-0.5 rounded font-mono">
                  {data.frames.length}
                </span>
              </div>
              {selectedMoldura !== defaultMoldura && (
                <button
                  onClick={handleSaveMoldura}
                  disabled={savingMoldura}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors disabled:opacity-50"
                >
                  {savingMoldura ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                  Save Default
                </button>
              )}
            </div>
            {data.frames.length === 0 ? (
              <div className="panel p-8 text-center">
                <div className="text-zinc-500 text-sm">No frames found</div>
                <div className="text-xs text-zinc-600 mt-1">
                  Frames should be in 05-Assets/tokens/frames/
                </div>
              </div>
            ) : (
              <>
                <div className="text-[10px] text-zinc-500 mb-2">Click a frame to set as default for new tokens</div>
                <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10 gap-2">
                  {data.frames.map((framePath) => {
                    const filename = framePath.split('/').pop() ?? framePath
                    const isDefault = framePath === defaultMoldura
                    const isSelected = framePath === selectedMoldura
                    return (
                      <button
                        key={framePath}
                        onClick={() => setSelectedMoldura(framePath)}
                        className={`panel p-2 flex flex-col items-center gap-1 transition-colors text-left ${
                          isSelected
                            ? 'border border-primary/60 bg-primary/5'
                            : 'hover:border-zinc-600 border border-transparent'
                        }`}
                        title={filename}
                      >
                        <div className="w-16 h-16 overflow-hidden rounded-lg bg-surface-3 relative">
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
                          {isDefault && (
                            <div className="absolute top-0.5 right-0.5 w-3 h-3 bg-primary rounded-full" title="Current default" />
                          )}
                        </div>
                        <div className="text-[9px] text-center truncate w-full font-mono" title={filename}>
                          <span className={isSelected ? 'text-primary' : 'text-zinc-600'}>{filename}</span>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
