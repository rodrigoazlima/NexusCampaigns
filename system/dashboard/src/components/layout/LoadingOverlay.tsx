'use client'

import { useEffect, useState } from 'react'

export default function LoadingOverlay() {
  const [visible, setVisible] = useState(true)
  const [fading, setFading] = useState(false)

  useEffect(() => {
    document.body.style.overflow = 'hidden'

    const finish = () => {
      setFading(true)
      setTimeout(() => {
        setVisible(false)
        document.body.style.overflow = ''
      }, 500)
    }

    if (document.readyState === 'complete') {
      finish()
    } else {
      window.addEventListener('load', finish)
      return () => window.removeEventListener('load', finish)
    }
  }, [])

  if (!visible) return null

  return (
    <div
      className={`fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-surface transition-opacity duration-500 ${
        fading ? 'opacity-0' : 'opacity-100'
      }`}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/logo-monogram-variant-square.png"
        alt="Nexus Campaigns"
        className="w-20 h-20 animate-pulse"
      />
      <div className="text-xs font-semibold tracking-widest text-zinc-500 uppercase">
        Loading
      </div>
    </div>
  )
}
