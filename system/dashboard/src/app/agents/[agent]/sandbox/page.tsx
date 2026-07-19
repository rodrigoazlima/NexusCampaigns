export const dynamic = 'force-dynamic'

import { notFound } from 'next/navigation'
import Link from 'next/link'
import { readAgents, readAgentSandbox, readSandboxRuns } from '@/lib/vault'
import PageHeader from '@/components/widgets/PageHeader'
import AutoRefresh from '@/components/AutoRefresh'
import SandboxConfigForm from '@/components/agents/SandboxConfigForm'
import { Box } from 'lucide-react'
import { agentDisplayName } from '@/lib/utils'

type Params = { params: Promise<{ agent: string }> }

export default async function AgentSandboxPage({ params }: Params) {
  const { agent } = await params
  const info = readAgents().find((a) => a.name === agent)
  if (!info) notFound()

  const settings = readAgentSandbox(agent)
  const runs = readSandboxRuns()
    .filter((r) => r.agent === agent)
    .slice(0, 10)

  return (
    <div className="p-4 md:p-6">
      <AutoRefresh />
      <PageHeader
        icon={Box}
        title={`${agentDisplayName(agent)} — Sandbox`}
        subtitle="Route this agent's runs through an isolated container - only its declared knowledge-base/state changes reach the real vault"
      />

      <SandboxConfigForm agent={agent} initial={settings} />

      <div className="panel overflow-hidden mt-6">
        <div className="px-4 py-3 border-b border-surface-3 flex items-center justify-between">
          <div className="text-sm font-semibold text-zinc-200">Recent Sandbox Runs</div>
          <Link href="/log/changes" className="text-xs text-primary hover:underline">
            View all &rarr;
          </Link>
        </div>
        {runs.length === 0 ? (
          <div className="p-6 text-center text-zinc-500 text-sm">No sandbox runs yet for this agent.</div>
        ) : (
          <div className="divide-y divide-surface-3">
            {runs.map((r) => (
              <div key={r.runId} className="px-4 py-2.5 flex items-center justify-between gap-3 text-xs font-mono">
                <span className="text-zinc-500">{r.startedAt}</span>
                {r.dryRun && (
                  <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning">
                    dry-run
                  </span>
                )}
                <span className={r.containerExitCode === 0 ? 'text-success' : 'text-danger'}>
                  exit {r.containerExitCode}
                </span>
                <span className="text-success">{r.summary.applied} applied</span>
                <span className="text-warning">{r.summary.dropped} dropped</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
