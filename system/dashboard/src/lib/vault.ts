import fs from 'fs'
import path from 'path'
import { execSync } from 'child_process'
import { randomUUID } from 'crypto'
import matter from 'gray-matter'
import { parse as parseYaml } from 'yaml'
import type {
  AgentInfo,
  AgentRun,
  AgentStatus,
  QueueItem,
  QueueStats,
  ReviewItem,
  DraftRef,
  ItemDetail,
  ImageClassification,
  TokenConfig,
  PipelineData,
  LogLine,
  DailyReport,
  VaultStats,
  InboxImage,
  TokenFile,
  AgentConfig,
  AgentDoc,
  IntelligenceConfig,
  CampaignFrame,
} from './types'
import { addSeconds } from './utils'
import { resolveStatus } from './queue-status'

export const PROJECT_ROOT =
  process.env.PROJECT_ROOT ?? path.resolve(process.cwd(), '..', '..')
export const VAULT_ROOT =
  process.env.VAULT_ROOT ?? path.join(PROJECT_ROOT, '.knowledge-base')

const AGENTS_DIR = path.join(PROJECT_ROOT, 'agents')
const STATE_DIR = path.join(PROJECT_ROOT, 'agents', 'runtime', 'state')
const SHARED_DIR = path.join(PROJECT_ROOT, 'system', 'state')
const REPORTS_DIR = path.join(PROJECT_ROOT, 'system', 'state', 'review', 'reports')
const LOGS_DIR = path.join(PROJECT_ROOT, 'agents', 'runtime', 'state', 'logs')
const REGISTRY_PATH = path.join(PROJECT_ROOT, 'agents', 'registry.yaml')

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// gray-matter (js-yaml) auto-parses unquoted YAML date scalars (created: 2026-07-15)
// into JS Date objects, not strings — coerce back to the vault's ISO YYYY-MM-DD.
function frontmatterDate(v: unknown): string {
  if (v instanceof Date) return v.toISOString().slice(0, 10)
  return typeof v === 'string' ? v : ''
}

function readJson<T>(filePath: string): T | null {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8').trim()
    if (!raw) return null
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

function intelligenceLabel(dispatch: IntelligenceConfig): string {
  const type = dispatch.type
  let model: string | null = null
  if (type === 'claude-api') model = dispatch.claude_api?.model ?? null
  else if (type === 'openai-api') model = dispatch.openai_api?.model ?? null
  else if (type === 'gemini-api') model = dispatch.gemini_api?.model ?? null
  else if (type === 'openrouter-api') model = dispatch.openrouter_api?.model ?? null
  else if (type === 'codex-cli') model = dispatch.codex_cli?.model ?? null
  else if (type === 'lm-studio') model = dispatch.lm_studio?.model ?? null
  return model ? `${type} · ${model}` : type
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
    const tokenDir = path.join(PROJECT_ROOT, 'agents', 'token', 'state')
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
    reruns?: Record<string, number>
  }>>(path.join(SHARED_DIR, 'inbox-queue.json'))

  if (!raw) {
    return { total: 0, pending: 0, done: 0, stuck: 0, paused: 0, error: 0, byType: {}, items: [] }
  }

  const draftBySource = draftBySourceMap()
  const items: QueueItem[] = Object.entries(raw).map(([p, v]) => {
    const draft = draftBySource.get(p.replace(/\\/g, '/'))
    return {
      path: p,
      ingestedAt: v.ingestedAt,
      updatedAt: draft?.updated || v.ingestedAt,
      type: v.type,
      agents: v.agents,
      // tolerate the legacy single-int shape from earlier builds
      reruns: v.reruns && typeof v.reruns === 'object' ? v.reruns : {},
      entityId: draft ? (draft.uuid || draft.id) : null,
    }
  })

  const byType: Record<string, number> = {}
  let pending = 0
  let done = 0
  let stuck = 0
  let paused = 0
  let error = 0

  for (const item of items) {
    byType[item.type] = (byType[item.type] ?? 0) + 1
    switch (resolveStatus(item)) {
      case 'done': done++; break
      case 'error': error++; break
      case 'paused': paused++; break
      case 'stuck': stuck++; break
      case 'pending': pending++; break
    }
  }

  return { total: items.length, pending, done, stuck, paused, error, byType, items }
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

interface RegistryWorker {
  kind?: 'queue' | 'scheduled'
  enabled?: boolean
  batch_size?: number
  interval_seconds?: number
}

interface Registry {
  agents: Record<string, RegistryAgent>
  workers?: Record<string, RegistryWorker>
  pipeline_mode?: 'sync' | 'async'
}

const WORKER_DESCRIPTIONS: Record<string, string> = {
  ingestion: 'Vault ingestion — emoji-strip filenames, convert DOCX, register inbox queue.',
  thumbnails: 'Pre-generate 320px webp thumbnails for inbox images.',
  token: 'Generate 512×512 VTT tokens from classified portrait images.',
  wikilink: 'Link 02-Library entities via wikilinks.',
  shortfiles: 'Flag drafts under 10 body lines for reprocessing.',
  report: 'Pipeline health + pending-review report.',
  cleanup: 'Prune old logs/reports, trim agent-metrics history.',
  maintenance: 'Pipeline self-healing — stale locks, missing dirs, queue validation.',
}

// Worker metrics rows use {at, processed, failed, durationMs} (worker
// contract §Metrics) — normalize to the AgentRun shape the UI renders.
function normalizeRuns(runs: Array<Record<string, unknown>>): AgentRun[] {
  return runs.map((r) => ({
    startedAt: (r.startedAt ?? r.at ?? '') as string,
    finishedAt: (r.finishedAt ?? r.at ?? '') as string,
    durationMs: (r.durationMs ?? 0) as number,
    itemsProcessed: (r.itemsProcessed ?? r.processed ?? 0) as number,
    itemsFailed: (r.itemsFailed ?? r.failed ?? 0) as number,
  }))
}

const RUNTIME_SERVICE_NAME = 'vault-knowledge-factory'
const LOCK_STALE_SECONDS = 1800

function readRuntimeStatus(): AgentStatus {
  // Active cycle: lock file exists and is not stale
  try {
    const lockPath = path.join(STATE_DIR, 'runner.lock')
    const data = JSON.parse(fs.readFileSync(lockPath, 'utf-8'))
    const ageSeconds = (Date.now() - new Date(data.startedAt).getTime()) / 1000
    if (ageSeconds < LOCK_STALE_SECONDS) return 'running'
  } catch {
    // no lock file — normal between cycles
  }

  // Windows service check
  try {
    const out = execSync(`sc query ${RUNTIME_SERVICE_NAME}`, {
      encoding: 'utf-8',
      timeout: 2000,
    })
    if (out.includes('RUNNING')) return 'idle'
    if (out.includes('STOPPED') || out.includes('STOP_PENDING')) return 'offline'
  } catch {
    // service not installed
  }

  return 'offline'
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
    if (key === 'runtime') {
      status = readRuntimeStatus()
    } else if (regAgent.status === 'active') {
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
      lastRunStr && regAgent.status === 'active' && key !== 'runtime'
        ? addSeconds(lastRunStr, intervalSeconds)
        : null

    const agentConfig = readJson<AgentConfig>(path.join(AGENTS_DIR, key, 'agent.json'))
    const taskConfig = agentConfig?.tasks[taskId] ?? (agentConfig ? Object.values(agentConfig.tasks)[0] : null)
    const intelligence = taskConfig ? intelligenceLabel(taskConfig.dispatch) : (regAgent.llm ?? 'none')
    const fallbackIntelligence = taskConfig?.fallback_dispatch
      ? intelligenceLabel(taskConfig.fallback_dispatch)
      : null

    agents.push({
      id: taskId,
      name: key,
      status,
      description: regAgent.description ?? '',
      intervalSeconds,
      llm: regAgent.llm ?? 'none',
      intelligence,
      fallbackIntelligence,
      lastRun: lastRunStr,
      nextRun,
      totalRuns,
      totalProcessed,
      totalFailed,
      avgDurationMs,
      recentRuns: runs.slice(-5),
    })
  }

  // Static workers (registry.yaml workers: block) — in-process, no agent.json.
  // kind: 'worker' on the metrics entry; lastRun lives under worker:<name>.
  for (const [key, w] of Object.entries(registry?.workers ?? {})) {
    const stateKey = `worker:${key}`
    const lastRunStr = tasks[stateKey]?.lastRun ?? null
    const runs = normalizeRuns(
      (metrics[key] as unknown as { runs?: Array<Record<string, unknown>> } | undefined)?.runs ?? []
    )

    const totalRuns = runs.length
    const totalProcessed = runs.reduce((s, r) => s + r.itemsProcessed, 0)
    const totalFailed = runs.reduce((s, r) => s + r.itemsFailed, 0)
    const avgDurationMs =
      totalRuns > 0 ? runs.reduce((s, r) => s + r.durationMs, 0) / totalRuns : 0

    const scheduled = w.kind === 'scheduled'
    const intervalSeconds = scheduled ? (w.interval_seconds ?? 900) : 60

    let status: AgentStatus = 'idle'
    if (w.enabled === false) {
      status = 'offline'
    } else if (scheduled && lastRunStr) {
      const elapsed = now - new Date(lastRunStr).getTime()
      if (elapsed > intervalSeconds * 2500) status = 'offline'
    }
    const lastRun = runs[runs.length - 1]
    if (status === 'idle' && lastRun && lastRun.itemsFailed > 0) status = 'error'

    agents.push({
      id: stateKey,
      name: key,
      status,
      description: WORKER_DESCRIPTIONS[key] ?? `${key} worker (${w.kind ?? 'queue'})`,
      intervalSeconds,
      llm: 'none',
      intelligence: scheduled ? 'worker · scheduled' : 'worker · queue',
      fallbackIntelligence: null,
      lastRun: lastRunStr,
      nextRun: scheduled && lastRunStr ? addSeconds(lastRunStr, intervalSeconds) : null,
      totalRuns,
      totalProcessed,
      totalFailed,
      avgDurationMs,
      recentRuns: runs.slice(-5),
    })
  }

  // Folders under agents/ that registry.yaml hasn't caught up with yet still
  // show up here (as planned, zero-metrics) so a new agent dir is never
  // silently missing from the dashboard. Workers have no agents/ folder, but
  // exclude their keys too so a stray leftover dir never double-renders.
  const knownKeys = new Set([
    ...Object.keys(agentEntries),
    ...Object.keys(registry?.workers ?? {}),
  ])
  let dirEntries: string[] = []
  try {
    dirEntries = fs.readdirSync(AGENTS_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !['tests', 'shared'].includes(d.name))
      .map((d) => d.name)
  } catch {
    // ignore
  }

  for (const key of dirEntries) {
    if (knownKeys.has(key)) continue
    agents.push({
      id: `${key}-agent`,
      name: key,
      status: 'planned',
      description: '',
      intervalSeconds: 3600,
      llm: 'none',
      intelligence: 'none',
      fallbackIntelligence: null,
      lastRun: null,
      nextRun: null,
      totalRuns: 0,
      totalProcessed: 0,
      totalFailed: 0,
      avgDurationMs: 0,
      recentRuns: [],
    })
  }

  return agents
}

/** Parses agents/{name}/AGENT.md frontmatter for the agent detail pages. */
export function readAgentDoc(name: string): AgentDoc | null {
  try {
    const raw = fs.readFileSync(path.join(AGENTS_DIR, name, 'AGENT.md'), 'utf-8')
    const { data } = matter(raw)
    return {
      name: data.name ?? name,
      purpose: typeof data.purpose === 'string' ? data.purpose.trim() : '',
      inputs: data.inputs ?? [],
      outputs: data.outputs ?? [],
      dependencies: data.dependencies ?? [],
      responsibilities: data.responsibilities ?? [],
      restrictions: data.restrictions ?? [],
      state_files: data.state_files ?? [],
      commit_scope: data.commit_scope ?? [],
      owned_tools: data.owned_tools ?? [],
    }
  } catch {
    return null
  }
}

/** Raw agents/{name}/agent.json, for dispatch/task config display. */
export function readAgentConfig(name: string): AgentConfig | null {
  return readJson<AgentConfig>(path.join(AGENTS_DIR, name, 'agent.json'))
}

// ---------------------------------------------------------------------------
// Review items (01-Processing)
// ---------------------------------------------------------------------------

/** True when a path points at a generated/manual token file rather than a source image. */
export function isTokenPath(p: string): boolean {
  const base = p.replace(/\\/g, '/').split('/').pop() ?? ''
  const stem = base.replace(/\.[^.]+$/, '')
  return stem.endsWith('-token') || stem.includes('.token')
}

// Internal draft carrying sort hints used only to pick a group's primary.
type RawDraft = ReviewItem & { _keyCount: number; _hasName: boolean }

/**
 * Read every md draft in 01-Processing as an ungrouped ReviewItem.
 * Drafts whose source is itself a token file are excluded — only source
 * images get review items; tokens are associated to their source elsewhere.
 */
function readRawDrafts(): RawDraft[] {
  const processingDir = path.join(VAULT_ROOT, '01-Processing')
  const drafts: RawDraft[] = []
  const tokenBySource = new Map<string, string>()
  for (const t of Object.values(readGeneratedTokens())) {
    tokenBySource.set(t.sourcePath, t.tokenPath)
  }

  let files: string[]
  try {
    files = fs.readdirSync(processingDir)
  } catch {
    return drafts
  }

  for (const file of files) {
    if (!file.endsWith('.md')) continue
    try {
      const filepath = path.join(processingDir, file)
      const raw = fs.readFileSync(filepath, 'utf-8')
      const { data, content } = matter(raw)
      const sources: string[] = Array.isArray(data.source) ? data.source : []
      const srcPath = sources[0] ?? null

      // Exclude drafts that describe a token file rather than a source image.
      if (srcPath && isTokenPath(srcPath)) continue

      const excerpt = content.replace(/#+\s/g, '').trim().slice(0, 160)

      // Resolve token path from generated-tokens index or filesystem
      let tokenPath: string | null = null
      if (srcPath) {
        const normSrc = srcPath.replace(/\\/g, '/')
        const indexed = tokenBySource.get(normSrc)
        if (indexed) {
          tokenPath = indexed
        } else {
          const srcBase = normSrc.replace(/\.[^.]+$/, '')
          const candidate = `${srcBase}-token.png`
          if (fs.existsSync(path.join(PROJECT_ROOT, candidate))) {
            tokenPath = candidate
          }
        }
      }

      drafts.push({
        filename: file,
        filepath,
        id: data.id ?? file.replace('.md', ''),
        uuid: typeof data.uuid === 'string' ? data.uuid : '',
        type: data.type ?? 'unknown',
        status: data.status ?? 'pending',
        quality: typeof data.quality === 'number' ? data.quality : 0,
        created: frontmatterDate(data.created),
        updated: frontmatterDate(data.updated),
        tags: Array.isArray(data.tags) ? data.tags : [],
        source: sources,
        reviewed: data.reviewed === true,
        relationships: Array.isArray(data.relationships) ? data.relationships : [],
        excerpt,
        tokenPath,
        history: [],
        _keyCount: Object.keys(data).length,
        _hasName: typeof data.name === 'string' && data.name.length > 0,
      })
    } catch {
      // skip malformed
    }
  }

  return drafts
}

// First draft per normalized source path (same pick as the old linear .find)
function draftBySourceMap(): Map<string, RawDraft> {
  const map = new Map<string, RawDraft>()
  for (const d of readRawDrafts()) {
    const src = d.source[0]?.replace(/\\/g, '/')
    if (src && !map.has(src)) map.set(src, d)
  }
  return map
}

function toDraftRef(d: ReviewItem): DraftRef {
  return {
    filename: d.filename,
    filepath: d.filepath,
    id: d.id,
    uuid: d.uuid,
    type: d.type,
    quality: d.quality,
    reviewed: d.reviewed,
  }
}

function stripRaw(d: RawDraft, history: DraftRef[]): ReviewItem {
  const { _keyCount: _k, _hasName: _h, ...rest } = d
  void _k; void _h
  return { ...rest, history }
}

// Order that decides which draft represents a group: richest/named first.
function draftPriority(a: RawDraft, b: RawDraft): number {
  if (a._hasName !== b._hasName) return a._hasName ? -1 : 1
  if (a._keyCount !== b._keyCount) return b._keyCount - a._keyCount
  if (a.quality !== b.quality) return b.quality - a.quality
  return a.filename.localeCompare(b.filename)
}

/**
 * Review items, one per source image. Multiple md drafts that share a source
 * (e.g. a body description + a full NPC statblock) collapse into a single item;
 * the remaining drafts are exposed via `history`.
 */
export function readReviewItems(): ReviewItem[] {
  const drafts = readRawDrafts()

  // Group by normalized source image; drafts without a source stay standalone.
  const groups = new Map<string, RawDraft[]>()
  for (const d of drafts) {
    const src = d.source[0] ? d.source[0].replace(/\\/g, '/') : `__nosrc__:${d.id}`
    const arr = groups.get(src)
    if (arr) arr.push(d)
    else groups.set(src, [d])
  }

  const items: ReviewItem[] = []
  for (const group of groups.values()) {
    group.sort(draftPriority)
    const [primary, ...rest] = group
    items.push(stripRaw(primary, rest.map(toDraftRef)))
  }

  return items.sort((a, b) => b.quality - a.quality)
}

/** Canon entities in 02-Library, one ReviewItem per file (no grouping). */
export function readLibraryItems(): ReviewItem[] {
  const libDir = path.join(VAULT_ROOT, '02-Library')
  const genTokens = readGeneratedTokens()
  const items: ReviewItem[] = []

  let files: string[]
  try {
    files = fs.readdirSync(libDir)
  } catch {
    return items
  }

  for (const file of files) {
    if (!file.endsWith('.md')) continue
    try {
      const filepath = path.join(libDir, file)
      const raw = fs.readFileSync(filepath, 'utf-8')
      const { data, content } = matter(raw)
      const sources: string[] = Array.isArray(data.source) ? data.source : []
      const srcPath = sources[0] ? sources[0].replace(/\\/g, '/') : null
      const excerpt = content.replace(/#+\s/g, '').trim().slice(0, 160)
      const tokenEntry = srcPath
        ? Object.values(genTokens).find((t) => t.sourcePath === srcPath)
        : undefined

      items.push({
        filename: file,
        filepath,
        id: data.id ?? file.replace('.md', ''),
        uuid: typeof data.uuid === 'string' ? data.uuid : '',
        type: data.type ?? 'unknown',
        status: data.status ?? 'approved',
        quality: typeof data.quality === 'number' ? data.quality : 0,
        created: frontmatterDate(data.created),
        updated: frontmatterDate(data.updated),
        tags: Array.isArray(data.tags) ? data.tags : [],
        source: sources,
        reviewed: data.reviewed === true,
        relationships: Array.isArray(data.relationships) ? data.relationships : [],
        excerpt,
        tokenPath: tokenEntry ? tokenEntry.tokenPath : null,
        history: [],
      })
    } catch {
      // skip malformed
    }
  }

  return items
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

/** Create a blank draft in 01-Processing. Throws if the slug already exists. */
export function createDraft(opts: {
  id: string
  type: string
  body: string
  extra?: Record<string, unknown>
}): { filename: string; uuid: string } {
  const today = new Date().toISOString().split('T')[0]
  const filename = `${opts.id}.md`
  const filepath = path.join(VAULT_ROOT, '01-Processing', filename)
  if (fs.existsSync(filepath)) {
    throw new Error(`Draft already exists: ${filename}`)
  }
  const uuid = randomUUID()
  const frontmatter = {
    id: opts.id,
    uuid,
    type: opts.type,
    status: 'draft',
    quality: 0,
    created: today,
    updated: today,
    tags: [],
    source: [],
    reviewed: false,
    relationships: [],
    ...opts.extra,
  }
  fs.writeFileSync(filepath, matter.stringify(opts.body, frontmatter), 'utf-8')
  return { filename, uuid }
}

// ---------------------------------------------------------------------------
// Campaign setting frame (03-Campaigns/, type: campaign) — campaign.md §3
// ---------------------------------------------------------------------------

const CAMPAIGNS_DIR = path.join(VAULT_ROOT, '03-Campaigns')

function frameFromData(file: string, data: Record<string, unknown>): CampaignFrame {
  return {
    id: typeof data.id === 'string' ? data.id : file.replace('.md', ''),
    pitch: typeof data.pitch === 'string' ? data.pitch : '',
    tone_primary: typeof data.tone_primary === 'string' ? data.tone_primary : '',
    tone_secondary: typeof data.tone_secondary === 'string' ? data.tone_secondary : '',
    scale: typeof data.scale === 'string' ? data.scale : '',
    central_tension: typeof data.central_tension === 'string' ? data.central_tension : '',
    player_buyin: typeof data.player_buyin === 'string' ? data.player_buyin : '',
    active: data.active === true,
  }
}

/** The active campaign frame: prefer `active: true`, else the first one found. */
export function readActiveCampaign(): CampaignFrame | null {
  let files: string[]
  try {
    files = fs.readdirSync(CAMPAIGNS_DIR).filter((f) => f.endsWith('.md'))
  } catch {
    return null
  }
  let first: CampaignFrame | null = null
  for (const file of files) {
    try {
      const { data } = matter(fs.readFileSync(path.join(CAMPAIGNS_DIR, file), 'utf-8'))
      if (data.type !== 'campaign') continue
      const frame = frameFromData(file, data as Record<string, unknown>)
      if (frame.active) return frame
      first ??= frame
    } catch {
      // skip malformed
    }
  }
  return first
}

/** Upsert the active campaign frame. ponytail: single active setting — multi-
 * campaign switching is deferred (campaign.md §3 "Switch setting ▾"). */
export function writeCampaign(frame: Omit<CampaignFrame, 'active'> & { id?: string }): CampaignFrame {
  const today = new Date().toISOString().split('T')[0]
  fs.mkdirSync(CAMPAIGNS_DIR, { recursive: true })

  const existing = readActiveCampaign()
  const id = frame.id || existing?.id ||
    `campaign-${frame.pitch ? frame.pitch.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) : 'setting'}` ||
    'campaign-setting'

  const filepath = path.join(CAMPAIGNS_DIR, `${id}.md`)
  let created = today
  if (fs.existsSync(filepath)) {
    try { created = frontmatterDate(matter(fs.readFileSync(filepath, 'utf-8')).data.created) || today } catch { /* keep today */ }
  }

  const data = {
    id, type: 'campaign', status: 'active', created, updated: today,
    pitch: frame.pitch, tone_primary: frame.tone_primary, tone_secondary: frame.tone_secondary,
    scale: frame.scale, central_tension: frame.central_tension, player_buyin: frame.player_buyin,
    active: true,
  }
  const body = `# ${frame.pitch || 'Untitled setting'}\n\n> ${frame.central_tension || 'The central tension of this setting.'}\n`
  fs.writeFileSync(filepath, matter.stringify(body, data), 'utf-8')
  return { ...data, active: true } as CampaignFrame
}

/**
 * Pull the NPC `## Want` one-liner and whether a `## Secret` is filled in.
 * ponytail: heading-scan heuristic; swap for a real md AST if sections move.
 * A line counts as real content only if it's non-empty and not a `>` blockquote
 * placeholder (the create skeleton seeds those prompts as blockquotes).
 */
export function parseWantSecret(filepath: string): { want: string | null; hasSecret: boolean } {
  let body = ''
  try {
    body = matter(fs.readFileSync(filepath, 'utf-8')).content
  } catch {
    return { want: null, hasSecret: false }
  }

  const sectionContent = (heading: string): string | null => {
    const lines = body.split('\n')
    const start = lines.findIndex((l) => l.trim().toLowerCase() === `## ${heading}`.toLowerCase())
    if (start === -1) return null
    for (let i = start + 1; i < lines.length; i++) {
      const line = lines[i].trim()
      if (line.startsWith('## ')) break // next section
      if (!line || line.startsWith('>')) continue // empty or placeholder prompt
      return line.replace(/^[-*]\s*/, '').replace(/\*\*/g, '')
    }
    return null
  }

  return { want: sectionContent('Want'), hasSecret: sectionContent('Secret') !== null }
}

const PRESSURE_TAGS = ['brute', 'swarm', 'social', 'puzzle']

/**
 * Bestiary heuristics (bestiary.md Deltas 4–6). `pressure`/`signature` come from
 * tags; `hasTerrain`/`hasNonCombat` scan the body so encounters missing those
 * sections can be flagged "flat" / "forced".
 * ponytail: same heading-scan + non-placeholder rule as parseWantSecret — a `>`
 * blockquote (the skeleton's seed) counts as empty, so the GM must fill plain text.
 */
export function parseBestiary(filepath: string, tags: string[]): {
  pressure: string | null
  signature: boolean
  hasTerrain: boolean
  hasNonCombat: boolean
} {
  let body = ''
  try {
    body = matter(fs.readFileSync(filepath, 'utf-8')).content
  } catch {
    return { pressure: null, signature: false, hasTerrain: false, hasNonCombat: false }
  }

  const filled = (heading: string): boolean => {
    const lines = body.split('\n')
    const start = lines.findIndex((l) => l.trim().toLowerCase() === `## ${heading}`.toLowerCase())
    if (start === -1) return false
    for (let i = start + 1; i < lines.length; i++) {
      const line = lines[i].trim()
      if (line.startsWith('## ')) break
      if (!line || line.startsWith('>')) continue
      // strip bullet + bold label + "label:" prefix; anything left = real content
      const rest = line.replace(/^[-*]\s*/, '').replace(/\*\*/g, '').replace(/^[^:]*:\s*/, '')
      if (rest) return true
    }
    return false
  }

  return {
    pressure: PRESSURE_TAGS.find((p) => tags.includes(p)) ?? null,
    signature: tags.includes('signature'),
    hasTerrain: filled('Terrain & hazards'),
    hasNonCombat: filled('Non-combat alternative'),
  }
}

/**
 * Faction heuristics (factions.md Deltas 4–6). `leader`/`stronghold`/`rival`
 * come from the first non-placeholder `[[wikilink]]` in their section; the clock
 * is the filled checklist under `## Clock` plus the frontmatter `clock_step`
 * position. ponytail: empty skeleton steps ("Step 1:") don't count as a clock.
 */
export function parseFaction(filepath: string): {
  leader: string | null
  stronghold: string | null
  rival: string | null
  clockSteps: string[]
  clockStep: number
} {
  let parsed
  try {
    parsed = matter(fs.readFileSync(filepath, 'utf-8'))
  } catch {
    return { leader: null, stronghold: null, rival: null, clockSteps: [], clockStep: 0 }
  }
  const lines = parsed.content.split('\n')

  // lines under the first `## <prefix>…` heading, up to the next `## ` heading
  const sectionLines = (prefix: string): string[] => {
    const start = lines.findIndex((l) => l.trim().toLowerCase().startsWith(`## ${prefix.toLowerCase()}`))
    if (start === -1) return []
    const out: string[] = []
    for (let i = start + 1; i < lines.length; i++) {
      if (lines[i].trim().startsWith('## ')) break
      out.push(lines[i])
    }
    return out
  }

  // first [[wikilink]] with a non-empty target (skeleton seeds an empty `[[ ]]`)
  const linkIn = (prefix: string): string | null => {
    for (const l of sectionLines(prefix)) {
      const m = l.match(/\[\[([^\]]*)\]\]/)
      if (m && m[1].trim()) return m[1].trim()
    }
    return null
  }

  const clockSteps = sectionLines('Clock')
    .map((l) => l.trim())
    .filter((l) => /^[-*]\s*\[[ xX]\]/.test(l))
    .map((l) => l.replace(/^[-*]\s*\[[ xX]\]\s*/, '').replace(/\*\*/g, '').replace(/^step\s*\d+:\s*/i, '').trim())
    .filter(Boolean)

  const rawStep = Number(parsed.data?.clock_step)
  const clockStep = Number.isFinite(rawStep) ? Math.max(0, Math.min(rawStep, clockSteps.length)) : 0

  return {
    leader: linkIn('Leadership'),
    stronghold: linkIn('Seat of power'),
    rival: linkIn('Rivalry'),
    clockSteps,
    clockStep,
  }
}

/**
 * Place heuristics (places.md Deltas 3–5). `controlledBy` is the first
 * non-placeholder `[[wikilink]]` in the Control section; `hasSensory` is true
 * when any Smell/Sound/Sight line under "Sensory hooks" carries real text.
 * ponytail: same heading-scan + non-placeholder rule as parseFaction/parseBestiary.
 */
export function parsePlace(filepath: string): {
  controlledBy: string | null
  hasSensory: boolean
} {
  let body = ''
  try {
    body = matter(fs.readFileSync(filepath, 'utf-8')).content
  } catch {
    return { controlledBy: null, hasSensory: false }
  }
  const lines = body.split('\n')

  const sectionLines = (prefix: string): string[] => {
    const start = lines.findIndex((l) => l.trim().toLowerCase().startsWith(`## ${prefix.toLowerCase()}`))
    if (start === -1) return []
    const out: string[] = []
    for (let i = start + 1; i < lines.length; i++) {
      if (lines[i].trim().startsWith('## ')) break
      out.push(lines[i])
    }
    return out
  }

  const controlledBy = (() => {
    for (const l of sectionLines('Control')) {
      const m = l.match(/\[\[([^\]]*)\]\]/)
      if (m && m[1].trim()) return m[1].trim()
    }
    return null
  })()

  // any Smell/Sound/Sight line with content past its "label:" prefix
  const hasSensory = sectionLines('Sensory hooks').some((l) => {
    const t = l.trim()
    if (!t || t.startsWith('>')) return false
    const rest = t.replace(/^[-*]\s*/, '').replace(/\*\*/g, '').replace(/^[^:]*:\s*/, '')
    return rest.length > 0
  })

  return { controlledBy, hasSensory }
}

const QUEST_SHAPES = ['job', 'mystery', 'moral']

/**
 * Quest heuristics (quests.md Deltas 4–7). `patron`/`place`/`reward` are the
 * first non-placeholder `[[wikilink]]` in their sections; `shape` + `openingHook`
 * come from tags / frontmatter; `branches` counts filled Path lines so a quest
 * with <2 is flagged a "rail". ponytail: same heading-scan + non-placeholder rule
 * as parseFaction/parsePlace — `>` blockquotes and bare `label:` lines count empty.
 */
export function parseQuest(filepath: string, tags: string[]): {
  shape: string | null
  openingHook: boolean
  patron: string | null
  place: string | null
  reward: string | null
  hasStakes: boolean
  deadline: string | null
  branches: number
} {
  let parsed
  try {
    parsed = matter(fs.readFileSync(filepath, 'utf-8'))
  } catch {
    return { shape: null, openingHook: false, patron: null, place: null, reward: null, hasStakes: false, deadline: null, branches: 0 }
  }
  const lines = parsed.content.split('\n')

  const sectionLines = (prefix: string): string[] => {
    const start = lines.findIndex((l) => l.trim().toLowerCase().startsWith(`## ${prefix.toLowerCase()}`))
    if (start === -1) return []
    const out: string[] = []
    for (let i = start + 1; i < lines.length; i++) {
      if (lines[i].trim().startsWith('## ')) break
      out.push(lines[i])
    }
    return out
  }

  const linkIn = (prefix: string): string | null => {
    for (const l of sectionLines(prefix)) {
      const m = l.match(/\[\[([^\]]*)\]\]/)
      if (m && m[1].trim()) return m[1].trim()
    }
    return null
  }

  // strip bullet + bold + "label:" prefix; non-empty remainder = real content
  const contentOf = (line: string): string => {
    const t = line.trim()
    if (!t || t.startsWith('>')) return ''
    return t.replace(/^[-*]\s*/, '').replace(/\*\*/g, '').replace(/^[^:]*:\s*/, '').trim()
  }

  const textIn = (prefix: string): string | null => {
    for (const l of sectionLines(prefix)) {
      const c = contentOf(l)
      if (c) return c
    }
    return null
  }

  const branches = sectionLines('Branches').filter((l) => contentOf(l)).length

  return {
    shape: QUEST_SHAPES.find((s) => tags.includes(s)) ?? null,
    openingHook: parsed.data?.opening_hook === true,
    patron: linkIn('Patron'),
    place: linkIn('Place'),
    reward: linkIn('Reward'),
    hasStakes: textIn('Stakes') !== null,
    deadline: textIn('Clock'),
    branches,
  }
}

/**
 * Treasure heuristics (treasures.md Deltas 4–6). Items/artifacts: `owner` is the
 * first non-placeholder `[[wikilink]]` in Desire, `hasHook` the Hook section
 * filled. Lore: `question`/`answer` are the filled Q/A sections, `hasReveal` a
 * non-placeholder link under "How it's discovered". `signature` comes from tags.
 * ponytail: same heading-scan + non-placeholder rule as parseQuest/parseFaction —
 * `>` blockquotes and bare `label:` lines count as empty.
 */
export function parseTreasure(filepath: string, tags: string[]): {
  owner: string | null
  hasHook: boolean
  signature: boolean
  question: boolean
  answer: boolean
  hasReveal: boolean
} {
  let body = ''
  try {
    body = matter(fs.readFileSync(filepath, 'utf-8')).content
  } catch {
    return { owner: null, hasHook: false, signature: false, question: false, answer: false, hasReveal: false }
  }
  const lines = body.split('\n')

  const sectionLines = (prefix: string): string[] => {
    const start = lines.findIndex((l) => l.trim().toLowerCase().startsWith(`## ${prefix.toLowerCase()}`))
    if (start === -1) return []
    const out: string[] = []
    for (let i = start + 1; i < lines.length; i++) {
      if (lines[i].trim().startsWith('## ')) break
      out.push(lines[i])
    }
    return out
  }

  const linkIn = (prefix: string): string | null => {
    for (const l of sectionLines(prefix)) {
      const m = l.match(/\[\[([^\]]*)\]\]/)
      if (m && m[1].trim()) return m[1].trim()
    }
    return null
  }

  const filled = (prefix: string): boolean =>
    sectionLines(prefix).some((l) => {
      const t = l.trim()
      if (!t || t.startsWith('>')) return false
      return t.replace(/^[-*]\s*/, '').replace(/\*\*/g, '').replace(/^[^:]*:\s*/, '').trim().length > 0
    })

  return {
    owner: linkIn('Desire'),
    hasHook: filled('Hook'),
    signature: tags.includes('signature'),
    question: filled('The question'),
    answer: filled('The answer'),
    hasReveal: linkIn("How it's discovered") !== null,
  }
}

// ponytail: mtime+TTL memo, swap for fs.watch if staleness ever bites
let inboxCache: { mtimeMs: number; at: number; data: InboxImage[] } | null = null
const INBOX_CACHE_TTL_MS = 15_000

export function readInboxImages(): InboxImage[] {
  const queueFile = path.join(SHARED_DIR, 'inbox-queue.json')
  let mtimeMs = 0
  try {
    mtimeMs = fs.statSync(queueFile).mtimeMs
  } catch {
    return []
  }
  if (
    inboxCache &&
    inboxCache.mtimeMs === mtimeMs &&
    Date.now() - inboxCache.at < INBOX_CACHE_TTL_MS
  ) {
    return inboxCache.data
  }

  const raw = readJson<Record<string, {
    ingestedAt: string
    type: string
    agents: Record<string, string>
  }>>(queueFile)

  if (!raw) return []

  const imageExts = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
  const cutoff24h = Date.now() - 24 * 60 * 60 * 1000
  const results: InboxImage[] = []

  const draftBySource = draftBySourceMap()

  // One readdir per unique directory instead of one existsSync per image
  const dirListings = new Map<string, Set<string>>()
  const listDir = (dir: string): Set<string> => {
    let names = dirListings.get(dir)
    if (!names) {
      try {
        names = new Set(fs.readdirSync(dir))
      } catch {
        names = new Set()
      }
      dirListings.set(dir, names)
    }
    return names
  }

  for (const [queuePath, entry] of Object.entries(raw)) {
    const filename = path.basename(queuePath)
    const ext = path.extname(filename).toLowerCase()
    if (!imageExts.has(ext)) continue

    const absolutePath = path.join(PROJECT_ROOT, queuePath)
    const dir = path.dirname(absolutePath)
    const dirNames = listDir(dir)
    // Stale queue entries (file deleted from disk) would render as blank cards
    if (!dirNames.has(filename)) continue
    const base = filename.replace(/\.[^.]+$/, '')
    const tokenFilename = `${base}-token.png`
    const hasToken = dirNames.has(tokenFilename)
    const tokenPath = hasToken
      ? path.relative(PROJECT_ROOT, path.join(dir, tokenFilename)).replace(/\\/g, '/')
      : null

    const agentStatuses = Object.values(entry.agents)
    const anyPending = agentStatuses.some((s) => s === 'pending')
    const anyPaused = agentStatuses.some((s) => s === 'paused')
    const allDone = agentStatuses.every((s) => s === 'done' || s === 'skip')
    const ingestedTime = new Date(entry.ingestedAt).getTime()
    const isStuck = anyPending && !isNaN(ingestedTime) && ingestedTime < cutoff24h

    const normQueuePath = queuePath.replace(/\\/g, '/')
    const draft = draftBySource.get(normQueuePath)
    const entityId = draft ? (draft.uuid || draft.id) : null

    results.push({
      path: normQueuePath,
      filename,
      type: 'image',
      ingestedAt: entry.ingestedAt,
      agentSlots: entry.agents,
      hasToken,
      tokenPath,
      isStuck,
      isPaused: anyPaused,
      isDone: allDone,
      tags: draft?.tags ?? [],
      entityId,
    })
  }

  // Latest first, but paused items always sink to the bottom of the list.
  results.sort((a, b) => {
    if (a.isPaused !== b.isPaused) return a.isPaused ? 1 : -1
    return new Date(b.ingestedAt).getTime() - new Date(a.ingestedAt).getTime()
  })

  inboxCache = { mtimeMs, at: Date.now(), data: results }
  return results
}

// ---------------------------------------------------------------------------
// Item detail (single review item by id)
// ---------------------------------------------------------------------------

const TOKEN_ELIGIBLE_TYPES = new Set(['portrait', 'body'])
const DEFAULT_MOLDURA = '.knowledge-base/00-Inbox/tokens/Molduras/moldura_default.png'
const TOKEN_CONFIG_PATH = path.join(PROJECT_ROOT, 'system', 'state', 'token-config.json')

export function readVisionState(): Record<string, Record<string, unknown>> {
  const visionPath = path.join(PROJECT_ROOT, 'agents', 'vision', 'state', 'processed-images.json')
  const raw = readJson<{ images: Record<string, Record<string, unknown>>; pathIndex: Record<string, string> }>(visionPath)
  return raw?.images ?? {}
}

export function readVisionPathIndex(): Record<string, string> {
  const visionPath = path.join(PROJECT_ROOT, 'agents', 'vision', 'state', 'processed-images.json')
  const raw = readJson<{ images: Record<string, unknown>; pathIndex: Record<string, string> }>(visionPath)
  return raw?.pathIndex ?? {}
}

/** Look up an already-ingested image by content hash (blake2b-32, see nexus.shared.hashing). */
export function findImageByHash(hash: string): { path: string; originalName: string } | null {
  const entry = readVisionState()[hash]
  if (!entry) return null
  return { path: String(entry.path ?? ''), originalName: String(entry.originalName ?? '') }
}

export function readGeneratedTokens(): Record<string, { sourcePath: string; tokenPath: string; generatedAt: string }> {
  const genPath = path.join(PROJECT_ROOT, 'system', 'state', 'workers', 'token', 'generated-tokens.json')
  return readJson<Record<string, { sourcePath: string; tokenPath: string; generatedAt: string }>>(genPath) ?? {}
}

export function readTokenConfig(): TokenConfig {
  const cfg = readJson<TokenConfig>(TOKEN_CONFIG_PATH)
  return cfg ?? { molduraPath: DEFAULT_MOLDURA }
}

export function writeTokenConfig(cfg: TokenConfig): void {
  const dir = path.dirname(TOKEN_CONFIG_PATH)
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(TOKEN_CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf-8')
}

export function readReviewItemById(id: string): ReviewItem | null {
  // Resolve against every draft (not just group primaries) so any md id — e.g.
  // both `body-dragon-fire` and `npc-dragon-fire-body-a0` — opens its detail view.
  // UUID takes priority so stable URLs survive slug/filename renames.
  const drafts = readRawDrafts()
  const match = drafts.find((d) => d.uuid === id) ?? drafts.find((d) => d.id === id)
  if (match) {
    // History = the other drafts that share this draft's source image.
    const src = match.source[0] ? match.source[0].replace(/\\/g, '/') : null
    const siblings = src
      ? drafts.filter((d) => d !== match && d.source[0] && d.source[0].replace(/\\/g, '/') === src)
      : []
    return stripRaw(match, siblings.map(toDraftRef))
  }

  // Not a draft — fall back to canon (02-Library) so gm/view also opens approved entities.
  const library = readLibraryItems()
  return library.find((d) => d.uuid === id) ?? library.find((d) => d.id === id) ?? null
}

export function readItemDetail(id: string): ItemDetail | null {
  const item = readReviewItemById(id)
  if (!item) return null

  const visionImages = readVisionState()
  const pathIndex = readVisionPathIndex()
  const genTokens = readGeneratedTokens()
  const agents = readAgents().filter((a) => a.status !== 'planned')

  // Resolve vision classification by source image path
  let imageClassification: ImageClassification | null = null
  let tokenPath: string | null = null
  let tokenEligible = false
  let tokenUpdatedAt: string | null = null

  const sourceFile = item.source[0] ?? null
  if (sourceFile) {
    const inboxRelPath = sourceFile.replace(/\\/g, '/')
    const sha256Key = pathIndex[inboxRelPath]
    const visionEntry = sha256Key ? visionImages[sha256Key] : null
    if (visionEntry) {
      const v = visionEntry as Record<string, unknown>
      const imgType = String(v.type ?? 'unknown')
      imageClassification = {
        type: imgType,
        ancestry: String(v.ancestry ?? 'none'),
        char_class: String(v.char_class ?? v.class ?? 'none'),
        creature_type: String(v.creature_type ?? 'none'),
        element: String(v.element ?? 'none'),
        environment: String(v.environment ?? 'none'),
        description: String(v.description ?? ''),
        sha256: String(v.sha256 ?? ''),
        isToken: Boolean(v.isToken),
      }
      tokenEligible = TOKEN_ELIGIBLE_TYPES.has(imgType)
    }

    // Find token by source path
    const tokenEntry = Object.values(genTokens).find((t) => t.sourcePath === inboxRelPath)
    if (tokenEntry) {
      tokenPath = tokenEntry.tokenPath
      tokenUpdatedAt = tokenEntry.generatedAt
    } else {
      // Also check for *-token.png alongside the source
      const srcBase = sourceFile.replace(/\.[^.]+$/, '')
      const candidateToken = `${srcBase}-token.png`
      if (fs.existsSync(path.join(PROJECT_ROOT, candidateToken))) {
        tokenPath = candidateToken
      }
    }

    if (tokenPath && !tokenUpdatedAt) {
      try {
        tokenUpdatedAt = String(fs.statSync(path.join(PROJECT_ROOT, tokenPath)).mtimeMs)
      } catch {
        // file may not exist yet — leave unset
      }
    }
  }

  return {
    ...item,
    imageClassification,
    tokenPath,
    tokenUpdatedAt,
    tokenEligible,
    activeAgents: agents,
    sourceAbsolute: item.source.map((s) => path.join(PROJECT_ROOT, s)),
    tokenAbsolute: tokenPath ? path.join(PROJECT_ROOT, tokenPath) : null,
  }
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
