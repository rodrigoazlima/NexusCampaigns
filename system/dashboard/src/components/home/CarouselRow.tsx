'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import useEmblaCarousel from 'embla-carousel-react'
import Link from 'next/link'
import { ChevronLeft, ChevronRight, ArrowRight } from 'lucide-react'
import { PILLARS } from '@/lib/pillars'
import type { ReviewItem } from '@/lib/types'

type Entry = ReviewItem & { origin: 'draft' | 'canon' }

const AUTO_ADVANCE_MS = 3000
const RING_CIRCUMFERENCE = 2 * Math.PI * 16

function Poster({ e }: { e: Entry }) {
  const src = e.tokenPath || e.source[0]
  const href = `/gm/view/${e.uuid || encodeURIComponent(e.id)}`
  return (
    <Link
      href={href}
      className="group/card relative flex-shrink-0 w-32 sm:w-36 aspect-[2/3] rounded-lg overflow-hidden bg-surface-3 border border-surface-3 hover:border-primary/40 transition-colors"
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`/api/image?path=${encodeURIComponent(src)}`}
          alt=""
          className="w-full h-full object-cover transition-transform duration-300 group-hover/card:scale-105"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-2xl font-bold uppercase text-zinc-600">
          {e.type.slice(0, 3)}
        </div>
      )}
      <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/90 via-black/50 to-transparent">
        <div className="text-xs font-mono text-white truncate">{e.id}</div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className="text-[9px] font-mono text-zinc-300">Q{e.quality}</span>
          {e.origin === 'canon' && <span className="text-[9px] px-1 py-0.5 rounded bg-success/20 text-success">canon</span>}
        </div>
      </div>
    </Link>
  )
}

// Hover shows an inviting pulse; hold the hover 3s without clicking and it
// fires for you - the countdown ring is the affordance that tells the user
// that's about to happen (same idea as a "next episode" auto-play prompt).
function ArrowButton({
  direction, visible, onTrigger,
}: { direction: 'left' | 'right'; visible: boolean; onTrigger: () => void }) {
  const [hovering, setHovering] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = null
  }

  const handleEnter = () => {
    setHovering(true)
    clearTimer()
    timeoutRef.current = setTimeout(() => {
      onTrigger()
      setHovering(false)
    }, AUTO_ADVANCE_MS)
  }

  const handleLeave = () => {
    setHovering(false)
    clearTimer()
  }

  const handleClick = () => {
    clearTimer()
    setHovering(false)
    onTrigger()
  }

  useEffect(() => clearTimer, [])

  if (!visible) return null
  const Icon = direction === 'left' ? ChevronLeft : ChevronRight

  return (
    <button
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onClick={handleClick}
      aria-label={direction === 'left' ? 'Scroll left' : 'Scroll right'}
      className={`absolute ${direction === 'left' ? 'left-0' : 'right-0'} top-0 bottom-0 w-14 flex items-center justify-center ${
        direction === 'left' ? 'bg-gradient-to-r' : 'bg-gradient-to-l'
      } from-surface via-surface/80 to-transparent text-zinc-200 opacity-0 group-hover/row:opacity-100 transition-opacity duration-300`}
    >
      <span className={`relative flex items-center justify-center w-9 h-9 rounded-full bg-surface-3/90 border border-surface-4 transition-transform duration-500 ease-out ${hovering ? 'scale-110' : 'scale-100'}`}>
        <Icon size={18} />
        <svg className="absolute inset-0 -rotate-90" viewBox="0 0 36 36" aria-hidden>
          <circle cx="18" cy="18" r="16" fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth="2" />
          <circle
            cx="18" cy="18" r="16" fill="none" stroke="currentColor" strokeWidth="2"
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={hovering ? 0 : RING_CIRCUMFERENCE}
            style={{ transition: hovering ? `stroke-dashoffset ${AUTO_ADVANCE_MS}ms linear` : 'none' }}
          />
        </svg>
      </span>
    </button>
  )
}

export default function CarouselRow({ pillarKey, items }: { pillarKey: string; items: Entry[] }) {
  const pillar = PILLARS.find((p) => p.key === pillarKey)
  const [emblaRef, emblaApi] = useEmblaCarousel({ align: 'start', dragFree: true, containScroll: 'trimSnaps' })
  const [canPrev, setCanPrev] = useState(false)
  const [canNext, setCanNext] = useState(false)

  const onSelect = useCallback((api: NonNullable<typeof emblaApi>) => {
    setCanPrev(api.canScrollPrev())
    setCanNext(api.canScrollNext())
  }, [])

  useEffect(() => {
    if (!emblaApi) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- embla's own init pattern: sync initial button state from the api it just created
    onSelect(emblaApi)
    emblaApi.on('select', onSelect).on('reInit', onSelect)
  }, [emblaApi, onSelect])

  if (!pillar) return null
  const Icon = pillar.icon

  return (
    <section className="group/row relative">
      <Link href={pillar.href} className="group/link flex items-center gap-2 mb-3 w-fit">
        <Icon size={16} className={pillar.accent} />
        <h2 className="text-sm font-semibold text-zinc-100">{pillar.label}</h2>
        <span className="text-xs font-mono text-zinc-500">{items.length}</span>
        <ArrowRight size={14} className="text-zinc-600 opacity-0 group-hover/link:opacity-100 group-hover/link:translate-x-0.5 transition-all" />
      </Link>

      <div className="relative">
        <div ref={emblaRef} className="overflow-hidden">
          <div className="flex gap-3">
            {items.map((e) => <Poster key={e.id} e={e} />)}
          </div>
        </div>

        <ArrowButton direction="left" visible={canPrev} onTrigger={() => emblaApi?.scrollPrev()} />
        <ArrowButton direction="right" visible={canNext} onTrigger={() => emblaApi?.scrollNext()} />
      </div>
    </section>
  )
}
