import type { LucideIcon } from 'lucide-react'
import PageHeader from '@/components/widgets/PageHeader'
import { Hammer } from 'lucide-react'

interface ComingSoonProps {
  icon: LucideIcon
  title: string
  subtitle?: string
}

// Placeholder for scaffolded pillar pages that route but aren't built yet.
export default function ComingSoon({ icon, title, subtitle }: ComingSoonProps) {
  return (
    <div className="p-4 md:p-6">
      <PageHeader icon={icon} title={title} subtitle={subtitle} />
      <div className="panel p-12 text-center">
        <Hammer size={24} className="mx-auto text-zinc-600 mb-3" />
        <div className="text-zinc-400 text-sm">Coming soon</div>
        <div className="text-xs text-zinc-600 mt-1">
          This pillar is scaffolded — the page lands in a later phase.
        </div>
      </div>
    </div>
  )
}
