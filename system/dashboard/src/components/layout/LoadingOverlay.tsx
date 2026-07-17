'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'

export default function LoadingOverlay() {
  const pathname = usePathname()
  const [visible, setVisible] = useState(true)
  const [fading, setFading] = useState(false)
  const firstLoad = useRef(true)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }

  const show = () => {
    clearTimers()
    setFading(false)
    setVisible(true)
    document.body.style.overflow = 'hidden'
  }

  const hide = (delay = 0) => {
    clearTimers()
    timers.current.push(
      setTimeout(() => {
        setFading(true)
        timers.current.push(
          setTimeout(() => {
            setVisible(false)
            document.body.style.overflow = ''
          }, 500)
        )
      }, delay)
    )
  }

  // Initial page load - wait for assets, then reveal.
  useEffect(() => {
    if (document.readyState === 'complete') {
      hide()
    } else {
      const onLoad = () => hide()
      window.addEventListener('load', onLoad)
      return () => window.removeEventListener('load', onLoad)
    }
    return undefined
  }, [])

  // Route change finished (pathname committed) - reveal shortly after.
  useEffect(() => {
    if (firstLoad.current) {
      firstLoad.current = false
      return
    }
    hide(150)
  }, [pathname])

  // Route change started - lock immediately on internal link clicks / back-forward.
  useEffect(() => {
    // Capture phase: must run before Next's <Link> bubble handler calls
    // preventDefault() for client-side routing, or defaultPrevented is
    // already true by the time a bubble-phase listener would see it.
    const onClick = (e: MouseEvent) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      const anchor = (e.target as HTMLElement)?.closest('a')
      if (!anchor || anchor.target === '_blank') return
      const href = anchor.getAttribute('href')
      if (!href || href.startsWith('#')) return
      const url = new URL(href, window.location.href)
      if (url.origin !== window.location.origin) return
      if (url.pathname === window.location.pathname) return
      show()
    }
    const onPopState = () => show()
    document.addEventListener('click', onClick, true)
    window.addEventListener('popstate', onPopState)
    return () => {
      document.removeEventListener('click', onClick, true)
      window.removeEventListener('popstate', onPopState)
    }
  }, [])

  useEffect(() => () => clearTimers(), [])

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
