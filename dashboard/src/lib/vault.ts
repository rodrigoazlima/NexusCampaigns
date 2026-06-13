import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { parse as parseYaml } from 'yaml'
import type {
  AgentInfo,
  AgentRun,
  AgentStatus,
  QueueItem,
  QueueStats,
  ReviewItem,
  PipelineData,
  LogLine,
  DailyReport,
  VaultStats,
  InboxImage,
  TokenFile,
} from './types'
import { addSeconds } from './utils'

export const PROJECT_ROOT =
  process.env.PROJECT_ROOT ?? 'C:\\opt\\GitHub\\NexusCampaigns'
export const VAULT_ROOT =
  process.env.VAULT_ROOT ?? path.join(PROJECT_ROOT, 'knowledge-base')

const STATE_DIR = path.join(PROJECT_ROOT, '.agents', 'runtime', 'state')
const SHARED_DIR = path.join(PROJECT_ROOT, '.shared', 'state')
const REPORTS_DIR = path.join(PROJECT_ROOT, '.agents', 'review', 'state', 'reports')
const LOGS_DIR = path.join(PROJECT_ROOT, '.agents', 'runtime', 'state', 'logs')
const REGISTRY_PATH = path.join(PROJECT_ROOT, '.agents', 'registry.yaml')

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readJson<T>(filePath: string): T | null {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8').trim()
    if (!raw) return null
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

function countFiles(dir: string): number {
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    let count = 0
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue
      if (entry.isDirectory()) {
        count += countFiles(path.join(dir, entry.name))
      } else {
        count++
      }
    }
    return count
  } catch {
    return 0
  }
}

function countFilesByExt(dir: string, exts: string[]): number {
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    let count = 0
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue
      if (entry.isDirectory()) {
        count += countFilesByExt(path.join(dir, entry.name), exts)
      } else {
        const ext = path.extname(entry.name).toLowerCase()
        if (exts.includes(ext)) count++
      }
    }
    return count
  } catch {
    return 0
  }
}

// ---------------------------------------------------------------------------
// Vault stats
// ---------------------------------------------------------------------------

export function readVaultStats(): VaultStats {
  const inbox = countFiles(path.join(VAULT_ROOT, '00-Inbox'))
  const processing = countFiles(path.join(VAULT_ROOT, '01-Processing'))
  const library = countFiles(path.join(VAULT_ROOT, '02-Library'))
  const campaigns = countFiles(path.join(VAULT_ROOT, '03-Campaigns'))
  const relationships = countFiles(path.join(VAULT_ROOT, '04-Relationships'))
  const assets = countFiles(path.join(VAULT_ROOT, '05-Assets'))

  const imageExts = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']
  const totalImages = countFilesByExt(path.join(VAULT_ROOT, '00-Inbox'), imageExts)

  // Count NPCs in library
  let totalNpcs = 0
  let totalTokens = 0
  try {
    const libFiles = fs.readdirSync(path.join(VAULT_ROOT, '02-Library'))
    for (const f of libFiles) {
      if (!f.endsWith('.md')) continue
      try {
        const raw = fs.readFileSync(path.join(VAULT_ROOT, '02-Library', f), 'utf-8')
        const { data } = matter(raw)
        if (data.type === 'npc' || data.type === 'character') totalNpcs++
      } catch {
        // skip
      }
    }
  } catch {
    // skip
  }

  try {
    const tokenDir = path.join(PROJECT_ROOT, '.agents', 'token', 'state')
    if (fs.existsSync(tokenDir)) {
      totalTokens = countFilesByExt(tokenDir, ['.png', '.jpg', '.webp'])
    }
  } catch {
    // skip
  }

  return { inbox, processing, library, campaigns, assets, relationships, totalImages, totalNpcs, totalTokens }
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

export function readQueue(): QueueStats {
  const raw = readJson<Record<string, {
    ingestedAt: string
    type: string
    agents: Record<string, string>
  }>>(path.join(SHARED_DIR, 'inbox-queue.json'))

  if (!raw) {
    return { total: 0, pending: 0, done: 0, stuck: 0, byType: {}, items: [] }
  }

  const items: QueueItem[] = Object.entries(raw).map(([p, v]) => ({
    path: p,
    ingestedAt: v.ingestedAt,
    type: v.type,
    agents: v.agents,
  }))

  const byType: Record<string, number> = {}
  let pending = 0
  let done = 0
  let stuck = 0

  const cutoff24h = Date.now() - 24 * 60 * 60 * 1000

  for (const item of items) {
    byType[item.type] = (byType[item.type] ?? 0) + 1
    const agentStatuses = Object.values(item.agents)
    const allDone = agentStatuses.every((s) => s === 'done' || s === 'skip')
    const anyPending = agentStatuses.some((s) => s === 'pending')
    if (allDone) {
      done++
    } else if (anyPending) {
      const ingestedTime = new Date(item.ingestedAt).getTime()
      if (!isNaN(ingestedTime) && ingestedTime < cutoff24h) {
        stuck++
      } else {
        pending++
      }
    }
  }

  return { total: items.length, pending, done, stuck, byType, items }
}

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

interface RegistryAgent {
  status: string
  task_id?: string
  interval_seconds?: number
  description?: string
  llm?: string
}

interface Registry {
  agents: Record<string, RegistryAgent>
}

export function readAgents(): AgentInfo[] {
  let registry: Registry | null = null
  try {
    const raw = fs.readFileSync(REGISTRY_PATH, 'utf-8')
    registry = parseYaml(raw) as Registry
  } catch {
    // ignore
  }

  const tasks = readJson<Record<string, { lastRun: string }>>(
    path.join(STATE_DIR, 'tasks-state.json')
  ) ?? {}

  const metrics = readJson<Record<string, { runs: AgentRun[] }>>(
    path.join(STATE_DIR, 'agent-metrics.json')
  ) ?? {}

  const now = Date.now()
  const agents: AgentInfo[] = []

  const agentEntries = registry?.agents ?? {}

  for (const [key, regAgent] of Object.entries(agentEntries)) {
    const taskId = regAgent.task_id ?? `${key}-agent`
    const intervalSeconds = regAgent.interval_seconds ?? 3600
    const lastRunStr = tasks[taskId]?.lastRun ?? null
    const runs: AgentRun[] = metrics[taskId]?.runs ?? []

    const totalRuns = runs.length
    const totalProcessed = runs.reduce((s, r) => s + r.itemsProcessed, 0)
    const totalFailed = runs.reduce((s, r) => s + r.itemsFailed, 0)
    const avgDurationMs =
      totalRuns > 0 ? runs.reduce((s, r) => s + r.durationMs, 0) / totalRuns : 0

    let status: AgentStatus = 'planned'
    if (regAgent.status === 'active') {
      if (!lastRunStr) {
        status = 'offline'
      } else {
        const lastRunTime = new Date(lastRunStr).getTime()
        const elapsed = now - lastRunTime
        if (elapsed < intervalSeconds * 2500) {
          status = 'idle'
        } else {
          status = 'offline'
        }
        // Check last run for failures
        const lastRun = runs[runs.length - 1]
        if (lastRun && lastRun.itemsFailed > 0) {
          status = 'error'
        }
      }
    }

    const nextRun =
      lastRunStr && regAgent.status === 'active'
        ? addSeconds(lastRunStr, intervalSeconds)
        : null

    agents.push({
      id: taskId,
      name: key,
      status,
      description: regAgent.description ?? '',
      intervalSeconds,
      llm: regAgent.llm ?? 'none',
      lastRun: lastRunStr,
      nextRun,
      totalRuns,
      totalProcessed,
      totalFailed,
      avgDurationMs,
      recentRuns: runs.slice(-5),
    })
  }

  return agents
}

// ---------------------------------------------------------------------------
// Review items (01-Processing)
// ---------------------------------------------------------------------------

export function readReviewItems(): ReviewItem[] {
  const processingDir = path.join(VAULT_ROOT, '01-Processing')
  const items: ReviewItem[] = []

  try {
    const files = fs.readdirSync(processingDir)
    for (const file of files) {
      if (!file.endsWith('.md')) continue
      try {
        const filepath = path.join(processingDir, file)
        const raw = fs.readFileSync(filepath, 'utf-8')
        const { data, content } = matter(raw)
        const excerpt = content.replace(/#+\s/g, '').trim().slice(0, 160)
        items.push({
          filename: file,
          filepath,
          id: data.id ?? file.replace('.md', ''),
          type: data.type ?? 'unknown',
          status: data.status ?? 'pending',
          quality: typeof data.quality === 'number' ? data.quality : 0,
          created: data.created ?? '',
          updated: data.updated ?? '',
          tags: Array.isArray(data.tags) ? data.tags : [],
          source: Array.isArray(data.source) ? data.source : [],
          reviewed: data.reviewed === true,
          relationships: Array.isArray(data.relationships) ? data.relationships : [],
          excerpt,
        })
      } catch {
        // skip malformed
      }
    }
  } catch {
    // dir missing
  }

  return items.sort((a, b) => b.quality - a.quality)
}

// ---------------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------------

export function readPipeline(): PipelineData {
  const stages = [
    { name: 'Inbox', folder: '00-Inbox', count: 0, owner: 'ingestion', color: 'text-neutral' },
    { name: 'Processing', folder: '01-Processing', count: 0, owner: 'vision/lore/wiki', color: 'text-warning' },
    { name: 'Library', folder: '02-Library', count: 0, owner: 'human review', color: 'text-success' },
    { name: 'Campaigns', folder: '03-Campaigns', count: 0, owner: 'manual', color: 'text-primary' },
    { name: 'Assets', folder: '05-Assets', count: 0, owner: 'token', color: 'text-purple-400' },
    { name: 'Archive', folder: '99-Archive', count: 0, owner: 'cleanup', color: 'text-zinc-500' },
  ]

  for (const stage of stages) {
    stage.count = countFiles(path.join(VAULT_ROOT, stage.folder))
  }

  const librarySize = stages.find((s) => s.name === 'Library')?.count ?? 0
  const pendingReview = stages.find((s) => s.name === 'Processing')?.count ?? 0

  // Throughput: items that moved in last 24h (approximate from queue done items)
  const queue = readQueue()
  const throughput24h = queue.done

  return { stages, throughput24h, pendingReview, librarySize }
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------

const LOG_REGEX = /\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([^\]]+)\] (INFO|WARN|ERROR|DEBUG): (.+)/

export function readLogs(opts: {
  limit?: number
  severity?: string
  task?: string
} = {}): LogLine[] {
  const logFile = path.join(LOGS_DIR, 'automation.log')
  const lines: LogLine[] = []

  try {
    const raw = fs.readFileSync(logFile, 'utf-8')
    const rawLines = raw.split('\n').reverse()
    for (const line of rawLines) {
      const match = LOG_REGEX.exec(line.trim())
      if (!match) continue
      const [, timestamp, task, severity, message] = match
      if (opts.severity && severity !== opts.severity) continue
      if (opts.task && task !== opts.task) continue
      lines.push({
        timestamp,
        task,
        severity: severity as LogLine['severity'],
        message,
      })
      if (opts.limit && lines.length >= opts.limit) break
    }
  } catch {
    // log missing
  }

  return lines
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export function readLatestReport(): DailyReport | null {
  try {
    const files = fs
      .readdirSync(REPORTS_DIR)
      .filter((f) => f.startsWith('report-') && f.endsWith('.json'))
      .sort()
    if (files.length === 0) return null
    const latest = files[files.length - 1]
    return readJson<DailyReport>(path.join(REPORTS_DIR, latest))
  } catch {
    return null
  }
}

export function readAllReports(): Record<string, DailyReport> {
  const result: Record<string, DailyReport> = {}
  try {
    const files = fs
      .readdirSync(REPORTS_DIR)
      .filter((f) => f.startsWith('report-') && f.endsWith('.json'))
      .sort()
    for (const file of files) {
      const report = readJson<DailyReport>(path.join(REPORTS_DIR, file))
      if (report) {
        result[report.date ?? file.replace('report-', '').replace('.json', '')] = report
      }
    }
  } catch {
    // ignore
  }
  return result
}

// ---------------------------------------------------------------------------
// GM Write operations
// ---------------------------------------------------------------------------

export function writeFrontmatter(filepath: string, updates: Record<string, unknown>): void {
  try {
    const raw = fs.readFileSync(filepath, 'utf-8')
    const { data, content } = matter(raw)
    const mergedData = { ...data, ...updates }
    const output = matter.stringify(content, mergedData)
    fs.writeFileSync(filepath, output, 'utf-8')
  } catch (err) {
    throw new Error(`writeFrontmatter failed for ${filepath}: ${err}`)
  }
}

export function promoteToLibrary(srcFilepath: string): void {
  const filename = path.basename(srcFilepath)
  const destPath = path.join(VAULT_ROOT, '02-Library', filename)
  fs.copyFileSync(srcFilepath, destPath)
}

export function readInboxImages(): InboxImage[] {
  const raw = readJson<Record<string, {
    ingestedAt: string
    type: string
    agents: Record<string, string>
  }>>(path.join(SHARED_DIR, 'inbox-queue.json'))

  if (!raw) return []

  const imageExts = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
  const cutoff24h = Date.now() - 24 * 60 * 60 * 1000
  const results: InboxImage[] = []

  for (const [queuePath, entry] of Object.entries(raw)) {
    const filename = path.basename(queuePath)
    const ext = path.extname(filename).toLowerCase()
    if (!imageExts.has(ext)) continue

    const absolutePath = path.join(PROJECT_ROOT, queuePath)
    const dir = path.dirname(absolutePath)
    const base = filename.replace(/\.[^.]+$/, '')
    const tokenFilename = `${base}-token.png`
    const tokenAbsPath = path.join(dir, tokenFilename)
    const hasToken = fs.existsSync(tokenAbsPath)
    const tokenPath = hasToken
      ? path.relative(PROJECT_ROOT, tokenAbsPath).replace(/\\/g, '/')
      : null

    const agentStatuses = Object.values(entry.agents)
    const anyPending = agentStatuses.some((s) => s === 'pending')
    const ingestedTime = new Date(entry.ingestedAt).getTime()
    const isStuck = anyPending && !isNaN(ingestedTime) && ingestedTime < cutoff24h

    results.push({
      path: queuePath.replace(/\\/g, '/'),
      filename,
      type: 'image',
      ingestedAt: entry.ingestedAt,
      agentSlots: entry.agents,
      hasToken,
      tokenPath,
      isStuck,
    })
  }

  results.sort((a, b) => {
    if (a.isStuck && !b.isStuck) return -1
    if (!a.isStuck && b.isStuck) return 1
    return new Date(b.ingestedAt).getTime() - new Date(a.ingestedAt).getTime()
  })

  return results
}

function scanDirForTokens(dir: string, projectRoot: string, results: TokenFile[]): void {
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue
      const fullPath = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        scanDirForTokens(fullPath, projectRoot, results)
      } else if (entry.name.endsWith('-token.png')) {
        const relPath = path.relative(projectRoot, fullPath).replace(/\\/g, '/')
        const entityId = entry.name.replace('-token.png', '')
        results.push({ path: relPath, filename: entry.name, entityId })
      }
    }
  } catch {
    // ignore
  }
}

export function readTokenFiles(): { tokens: TokenFile[]; frames: string[] } {
  const tokens: TokenFile[] = []
  scanDirForTokens(path.join(VAULT_ROOT, '00-Inbox'), PROJECT_ROOT, tokens)

  const framesDir = path.join(VAULT_ROOT, '05-Assets', 'tokens', 'frames')
  let frames: string[] = []
  try {
    frames = fs
      .readdirSync(framesDir)
      .filter((f) => /\.(png|jpg|webp)$/i.test(f))
      .sort((a, b) => {
        const numA = parseInt(a.replace(/\D+/g, '') || '0', 10)
        const numB = parseInt(b.replace(/\D+/g, '') || '0', 10)
        return numA - numB
      })
      .map((f) =>
        path.relative(PROJECT_ROOT, path.join(framesDir, f)).replace(/\\/g, '/')
      )
  } catch {
    // ignore
  }

  return { tokens, frames }
}
