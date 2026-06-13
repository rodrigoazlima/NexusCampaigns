import { qualityColor, qualityLabel } from '@/lib/utils'

interface QualityBarProps {
  score: number
  showLabel?: boolean
}

export default function QualityBar({ score, showLabel = true }: QualityBarProps) {
  const pct = Math.min(100, Math.max(0, (score / 10) * 100))
  const color = qualityColor(score)
  const label = qualityLabel(score)

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-surface-3 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-zinc-400 w-4 text-right">{score}</span>
      {showLabel && (
        <span className={`text-xs ${score >= 7 ? 'text-success' : score >= 4 ? 'text-warning' : 'text-danger'}`}>
          {label}
        </span>
      )}
    </div>
  )
}
