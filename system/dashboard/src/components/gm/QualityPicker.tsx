interface QualityPickerProps {
  value: number | null
  onChange: (n: number) => void
}

function scoreClasses(score: number, selected: boolean): string {
  let base = ''
  if (score <= 3) {
    base = selected
      ? 'bg-danger text-white border-danger'
      : 'bg-danger/20 text-danger border-danger/30 hover:bg-danger/40'
  } else if (score <= 6) {
    base = selected
      ? 'bg-warning text-white border-warning'
      : 'bg-warning/20 text-warning border-warning/30 hover:bg-warning/40'
  } else {
    base = selected
      ? 'bg-success text-white border-success'
      : 'bg-success/20 text-success border-success/30 hover:bg-success/40'
  }
  return `text-xs font-mono font-semibold w-8 h-8 rounded border transition-colors ${base}`
}

export default function QualityPicker({ value, onChange }: QualityPickerProps) {
  return (
    <div>
      <div className="text-xs text-zinc-500 mb-1.5 uppercase tracking-wide font-semibold">
        Quality Score
      </div>
      <div className="flex gap-1">
        {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={scoreClasses(n, value === n)}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  )
}
