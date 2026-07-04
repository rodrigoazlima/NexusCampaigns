import fs from 'fs'
import path from 'path'
import { FileText } from 'lucide-react'
import { PROJECT_ROOT } from '@/lib/vault'
import type { PromptFile } from '@/lib/types'
import PageHeader from '@/components/widgets/PageHeader'
import PromptListClient from '@/components/prompts/PromptListClient'

export const dynamic = 'force-dynamic'

const AGENTS_DIR = path.resolve(path.join(PROJECT_ROOT, 'agents'))

function scanMd(dir: string): PromptFile[] {
  const results: PromptFile[] = []
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return results
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      results.push(...scanMd(full))
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      const rel = path.relative(AGENTS_DIR, full).replace(/\\/g, '/')
      const agent = rel.split('/')[0]
      const stat = fs.statSync(full)
      results.push({ path: rel, agent, filename: entry.name, sizeBytes: stat.size, modifiedAt: stat.mtime.toISOString() })
    }
  }
  return results
}

export default function PromptPage() {
  const files = scanMd(AGENTS_DIR).sort((a, b) => a.path.localeCompare(b.path))
  const agentCount = new Set(files.map((f) => f.agent)).size

  return (
    <div className="p-4 md:p-6">
      <PageHeader
        icon={FileText}
        title="Prompt Editor"
        subtitle={`${files.length} files across ${agentCount} agents`}
      />
      <PromptListClient files={files} />
    </div>
  )
}
