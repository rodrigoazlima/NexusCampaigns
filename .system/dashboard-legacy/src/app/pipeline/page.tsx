import { PageHeader } from '@/components/widgets/PageHeader'
import { cn } from '@/lib/utils'
import { getPipelineStats } from '@/lib/vault'
import { AutoRefresh } from '@/components/AutoRefresh'

export const dynamic = 'force-dynamic'

const PIPELINE_STEPS = [
  { id: 'raw',            label: 'Raw Assets',        icon: '📦', desc: 'Images, PDFs, DOCX, notes dropped into 00-Inbox' },
  { id: 'ingestion',      label: 'Ingestion Agent',   icon: '📥', desc: 'Filename normalisation, DOCX conversion, queue registration' },
  { id: 'vision',         label: 'Vision Agent',      icon: '👁', desc: 'Image classification via Qwen3-VL — type, race, class, element' },
  { id: 'lore',           label: 'Lore Agent',        icon: '📜', desc: 'NPC generation from images × scenarios, library-aware' },
  { id: 'classification', label: 'Classification',    icon: '🏷', desc: 'Tag enrichment, entity type inference, duplicate detection' },
  { id: 'wiki',           label: 'Wiki Agent',        icon: '🗂', desc: 'Doc-to-entity drafts with DM-focused markdown' },
  { id: 'review',         label: 'Human Review',      icon: '🧑', desc: 'Approve, reject, score, promote to canon' },
  { id: 'canon',          label: '02-Library',        icon: '📚', desc: 'Approved canon — NPCs, locations, factions, lore' },
]

export default function PipelinePage() {
  const data = getPipelineStats()

  return (
    <div className="animate-slide_in">
      <AutoRefresh />
      <PageHeader title="Pipeline" icon="⟶" subtitle="End-to-end flow from raw assets to approved canon" />

      <div className="p-6 space-y-6">

        {/* Stage counts */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {data.stages.map(stage => (
            <div key={stage.id} className="card p-3 text-center border-l-2" style={{ borderLeftColor: stage.color }}>
              <div className="text-xl mb-1">{stage.icon}</div>
              <div className="text-lg font-semibold text-white tabular-nums">{stage.count}</div>
              <div className="text-xs text-neutral mt-0.5">{stage.name}</div>
            </div>
          ))}
        </div>

        {/* Flow metrics */}
        <div className="grid grid-cols-3 gap-3">
          <Metric label="Flow 24h" value={data.totalFlow24h} sub="items processed" />
          <Metric label="Pending Review" value={data.pendingReview} sub="awaiting human" warn={data.pendingReview > 10} />
          <Metric label="In Library" value={data.libraryEntities} sub="approved canon" ok />
        </div>

        {/* Pipeline visualization */}
        <div className="card p-6">
          <div className="section-title mb-6">Pipeline Architecture</div>

          <div className="flex flex-col gap-0">
            {PIPELINE_STEPS.map((step, i) => (
              <div key={step.id} className="relative">
                {/* Connector */}
                {i > 0 && (
                  <div className="flex justify-center h-6">
                    <div className="w-px bg-surface-4 relative">
                      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-surface-4" />
                    </div>
                  </div>
                )}
                <StepBox step={step} highlight={step.id === 'review'} terminal={step.id === 'canon'} />
              </div>
            ))}
          </div>
        </div>

        {/* Agent → folder mapping */}
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-surface-3">
            <div className="section-title">Folder Ownership</div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-3 text-left">
                <Th>Folder</Th>
                <Th>Owner</Th>
                <Th>Files</Th>
                <Th>Purpose</Th>
              </tr>
            </thead>
            <tbody>
              {[
                { folder: '00-Inbox',        owner: 'Ingestion Agent',     files: data.stages[0].count, purpose: 'Raw unprocessed assets' },
                { folder: '01-Processing',   owner: 'Vision / Lore / Wiki', files: data.stages[1].count, purpose: 'AI-generated drafts pending review' },
                { folder: '02-Library',      owner: 'Human (promote)',      files: data.stages[3].count, purpose: 'Approved canon entities' },
                { folder: '03-Campaigns',    owner: 'Human',               files: data.stages[4].count, purpose: 'Campaign-specific refs to Library' },
                { folder: '04-Relationships',owner: 'Wiki Agent',           files: '—', purpose: 'Auto-generated knowledge graphs' },
                { folder: '05-Assets',       owner: 'Token Utility',        files: '—', purpose: 'Tokens, portraits, battlemaps' },
                { folder: '99-Archive',      owner: 'Human',               files: '—', purpose: 'Retired content — never delete' },
              ].map(row => (
                <tr key={row.folder} className="table-row-hover border-b border-surface-3/50">
                  <td className="px-4 py-2.5 font-mono text-xs text-primary/90">{row.folder}</td>
                  <td className="px-4 py-2.5 text-zinc-300">{row.owner}</td>
                  <td className="px-4 py-2.5 text-white tabular-nums">{row.files}</td>
                  <td className="px-4 py-2.5 text-neutral">{row.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

      </div>
    </div>
  )
}

function StepBox({ step, highlight, terminal }: { step: typeof PIPELINE_STEPS[0]; highlight?: boolean; terminal?: boolean }) {
  return (
    <div className={cn(
      'card mx-auto w-full max-w-2xl p-4 flex items-start gap-4',
      highlight && 'border-warning/40 bg-warning/5',
      terminal && 'border-success/40 bg-success/5',
    )}>
      <span className="text-2xl shrink-0">{step.icon}</span>
      <div>
        <div className="font-medium text-white">{step.label}</div>
        <div className="text-xs text-neutral mt-0.5">{step.desc}</div>
      </div>
    </div>
  )
}

function Metric({ label, value, sub, warn, ok }: { label: string; value: number; sub: string; warn?: boolean; ok?: boolean }) {
  return (
    <div className="card p-4 text-center">
      <div className={cn('text-2xl font-semibold tabular-nums', warn ? 'text-warning' : ok ? 'text-success' : 'text-white')}>{value}</div>
      <div className="text-sm text-white mt-0.5">{label}</div>
      <div className="text-xs text-neutral">{sub}</div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-xs font-medium text-neutral uppercase tracking-wide text-left">{children}</th>
}
