import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import type { LogLine, LogSeverity, VaultStats, AgentInfo, AgentStatus, QueueStats, QueueItem, FileType, AgentSlotStatus, PipelineStats, ReviewItem, ReviewStatus } from './types'

export const VAULT_ROOT = process.env.VAULT_ROOT ?? 'D:\\Library\\rpg\\dm\\pathway\\knowledge-base'
const AUTO_DIR = path.join(VAULT_ROOT, '.automation')

// ── JSON helpers ──────────────────────────────────────────────────────────

export function readJson<T>(relPath: string, fallback: T): T {
  try {
    const abs = path.isAbsolute(relPath) ? relPath : path.join(AUTO_DIR, relPath)
    return JSON.parse(fs.readFileSync(abs, 'utf-8').replace(/^﻿/, '')) as T
  } catch { return fallback }
}

// ── File counts ───────────────────────────────────────────────────────────

export function countFiles(dir: string, ext = '.md'): number {
  try {
    let n = 0
    function walk(d: string) {
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        if (e.isDirectory()) walk(path.join(d, e.name))
        else if (!ext || e.name.endsWith(ext)) n++
      }
    }
    walk(dir)
    return n
  } catch { return 0 }
}

export function countAllFiles(dir: string): number {
  return countFiles(dir, '')
}

// ── Frontmatter parser ────────────────────────────────────────────────────

export interface ParsedFrontmatter {
  id?: string
  type?: string
  status?: string
  quality?: number
  suggestedQuality?: number
  tags?: string[]
  source?: string[]
  reviewed?: boolean
  relationships?: string[]
  created?: string
  updated?: string
  description?: string
  title?: string
  sha256?: string
  agent_notes?: Record<string, string>
}

export function parseFrontmatter(filePath: string): ParsedFrontmatter & { body: string } {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8')
    const { data, content } = matter(raw)
    return { ...data as ParsedFrontmatter, body: content }
  } catch { return { body: '' } }
}

export function scanDirectory(dir: string): Array<{ path: string; fm: ParsedFrontmatter & { body: string } }> {
  const results: Array<{ path: string; fm: ParsedFrontmatter & { body: string } }> = []
  try {
    function walk(d: string) {
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const full = path.join(d, e.name)
        if (e.isDirectory()) walk(full)
        else if (e.name.endsWith('.md')) {
          results.push({ path: full.replace(VAULT_ROOT, '').replace(/\\/g, '/').replace(/^\//, ''), fm: parseFrontmatter(full) })
        }
      }
    }
    walk(dir)
  } catch {}
  return results
}

// ── Log parser ────────────────────────────────────────────────────────────

const LOG_RE = /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([^\]]+)\] (.+)$/

function severity(msg: string): LogSeverity {
  if (/\b(error|failed|exception|critical)\b/i.test(msg)) return 'error'
  if (/\b(warn|warning)\b/i.test(msg)) return 'warning'
  return 'info'
}

export function parseLog(limitLines = 500): LogLine[] {
  try {
    const logPath = path.join(AUTO_DIR, 'logs', 'automation.log')
    const raw = fs.readFileSync(logPath, 'utf-8')
    const lines = raw.split('\n').filter(Boolean)
    const tail = lines.slice(-limitLines)
    return tail
      .map(line => {
        const m = LOG_RE.exec(line.trim())
        if (!m) return null
        return { timestamp: m[1], taskId: m[2], message: m[3].trim(), severity: severity(m[3]) } as LogLine
      })
      .filter((x): x is LogLine => x !== null)
      .reverse()
  } catch { return [] }
}

export function parseLogSince(hoursAgo: number): LogLine[] {
  const cutoff = Date.now() - hoursAgo * 3600_000
  return parseLog(2000).filter(l => new Date(l.timestamp).getTime() >= cutoff)
}

// ── Tasks ─────────────────────────────────────────────────────────────────

export interface TaskConfig {
  id: string; script: string; intervalSeconds: number; description: string; model?: string
}
export interface TaskState {
  lastRun: string
}

export function readTasks(): TaskConfig[] {
  return readJson<{ tasks: TaskConfig[] }>('tasks.json', { tasks: [] }).tasks
}

export function readTaskState(): Record<string, TaskState> {
  return readJson<Record<string, TaskState>>('tasks-state.json', {})
}

// ── Reports ───────────────────────────────────────────────────────────────

export function latestReport() {
  try {
    const reportsDir = path.join(AUTO_DIR, 'reports')
    const files = fs.readdirSync(reportsDir)
      .filter(f => f.startsWith('report-') && f.endsWith('.json'))
      .sort().reverse()
    if (!files[0]) return null
    return JSON.parse(fs.readFileSync(path.join(reportsDir, files[0]), 'utf-8').replace(/^﻿/, ''))
  } catch { return null }
}

export function latestRepairReport(): { errorBuckets?: Record<string, number>; [k: string]: unknown } | null {
  try {
    const reportsDir = path.join(AUTO_DIR, 'reports')
    const files = fs.readdirSync(reportsDir)
      .filter(f => f.startsWith('repair-') && f.endsWith('.json'))
      .sort().reverse()
    if (!files[0]) return null
    return JSON.parse(fs.readFileSync(path.join(reportsDir, files[0]), 'utf-8').replace(/^﻿/, ''))
  } catch { return null }
}

export function allReports(): Record<string, unknown> {
  try {
    const reportsDir = path.join(AUTO_DIR, 'reports')
    const files = fs.readdirSync(reportsDir)
      .filter(f => f.startsWith('report-') && f.endsWith('.json'))
      .sort()
    const result: Record<string, unknown> = {}
    for (const f of files) {
      const dateStr = f.replace('report-', '').replace('.json', '')
      result[dateStr] = JSON.parse(fs.readFileSync(path.join(reportsDir, f), 'utf-8').replace(/^﻿/, ''))
    }
    return result
  } catch { return {} }
}

// ── Agent metrics ─────────────────────────────────────────────────────────

export interface AgentRun {
  startedAt: string
  finishedAt: string
  durationMs: number
  itemsProcessed: number
  itemsFailed: number
}

export interface AgentMetrics {
  runs: AgentRun[]
}

export function readAgentMetrics(): Record<string, AgentMetrics> {
  return readJson<Record<string, AgentMetrics>>('agent-metrics.json', {})
}

export function avgRunMs(metrics: Record<string, AgentMetrics>, agentId: string): number | null {
  const runs = metrics[agentId]?.runs
  if (!runs || runs.length === 0) return null
  const sum = runs.slice(0, 20).reduce((acc, r) => acc + (r.durationMs ?? 0), 0)
  return Math.round(sum / Math.min(runs.length, 20))
}

// ── SHA256-keyed image index helpers ──────────────────────────────────────

interface ImgEntry { path: string; type?: string; race?: string; sha256?: string; isToken?: boolean; status?: string }

function readImageIndices(): {
  bySha256: Record<string, ImgEntry>
  tokenBySha256: Record<string, string>
} {
  const processed = readJson<{
    version?: number
    images: Record<string, Partial<ImgEntry> & { sha256?: string }>
    pathIndex?: Record<string, string>
  }>('processed-images.json', { images: {} })

  const bySha256: Record<string, ImgEntry> = {}
  const pathToSha256: Record<string, string> = {}
  const version = processed.version ?? 1

  if (version >= 2 && processed.pathIndex) {
    for (const [sha256, entry] of Object.entries(processed.images)) {
      if (/^[0-9a-f]{64}$/i.test(sha256) && entry.path) {
        bySha256[sha256] = { path: entry.path, ...entry } as ImgEntry
        pathToSha256[entry.path] = sha256
      }
    }
    Object.assign(pathToSha256, processed.pathIndex)
  } else {
    // v1: path as key, sha256 as field
    for (const [imgPath, entry] of Object.entries(processed.images)) {
      if (entry.sha256 && entry.status === 'ok') {
        bySha256[entry.sha256] = { path: imgPath, ...entry } as ImgEntry
        pathToSha256[imgPath] = entry.sha256
      }
    }
  }

  const genTokens = readJson<{
    version?: number
    tokens: Record<string, { token?: string; tokenPath?: string; path?: string }>
  }>('generated-tokens.json', { tokens: {} })

  const tokenBySha256: Record<string, string> = {}

  if ((genTokens.version ?? 1) >= 2) {
    for (const [sha256, entry] of Object.entries(genTokens.tokens)) {
      const tp = entry.tokenPath ?? entry.token
      if (tp) tokenBySha256[sha256] = tp
    }
  } else {
    // v1: path as key — build sha256→token via pathToSha256 cross-reference
    for (const [imgPath, entry] of Object.entries(genTokens.tokens)) {
      const tp = entry.token
      if (!tp) continue
      const normPath = imgPath.replace(/\//g, '\\')
      const sha256 = pathToSha256[normPath] ?? pathToSha256[imgPath]
      if (sha256) tokenBySha256[sha256] = tp
    }
  }

  return { bySha256, tokenBySha256 }
}

export function findMarkdownByIdentifier(identifier: string): string | null {
  const processingDir = path.join(VAULT_ROOT, '01-Processing')
  if (/^[0-9a-f]{64}$/i.test(identifier)) {
    for (const { path: relPath, fm } of scanDirectory(processingDir)) {
      if (fm.sha256 === identifier) return path.join(VAULT_ROOT, relPath)
    }
    return null
  }
  const p = path.join(processingDir, `${identifier}.md`)
  return fs.existsSync(p) ? p : null
}

// ── Queue ─────────────────────────────────────────────────────────────────

export function readQueue(): Record<string, {
  ingestedAt: string; type: string; agents: Record<string, string>
}> {
  return readJson<Record<string, { ingestedAt: string; type: string; agents: Record<string, string> }>>('inbox-queue.json', {})
}

// ── Computed data (for server components — no HTTP round-trip) ────────────

export function getVaultStats(): VaultStats {
  const folders = {
    inbox:      countFiles(path.join(VAULT_ROOT, '00-Inbox')),
    processing: countFiles(path.join(VAULT_ROOT, '01-Processing')),
    library:    countFiles(path.join(VAULT_ROOT, '02-Library')),
    campaigns:  countFiles(path.join(VAULT_ROOT, '03-Campaigns')),
    assets:     countAllFiles(path.join(VAULT_ROOT, '05-Assets')),
    archive:    countFiles(path.join(VAULT_ROOT, '99-Archive')),
  }
  const processedImages = readJson<{ images?: Record<string, unknown> }>('processed-images.json', {})
  const imageEntries = Object.entries(processedImages.images ?? {})
  const classifiedCount = imageEntries.filter(([, v]) => (v as Record<string,string>)?.status === 'ok').length
  const genTokens = readJson<{ tokens?: Record<string, unknown> }>('generated-tokens.json', {})
  const tokenCount = Object.keys(genTokens.tokens ?? {}).length
  const processedNpcs = readJson<{ npcs?: Record<string, { status: string }> }>('processed-npcs.json', {})
  const npcEntries = Object.values(processedNpcs.npcs ?? {})
  return {
    folders,
    images: { total: imageEntries.length, classified: classifiedCount, withTokens: tokenCount },
    npcs: { total: npcEntries.length, approved: npcEntries.filter(n => n?.status === 'ok').length },
    growth: [],
  }
}

function nameFromDesc(description: string): string {
  const ci = description.indexOf(':')
  return ci > 0 ? description.slice(0, ci).trim() : description
}

export function getAgentInfo(): AgentInfo[] {
  const tasks   = readTasks()
  const state   = readTaskState()
  const logs    = parseLogSince(24)
  const metrics = readAgentMetrics()
  const logsByTask: Record<string, typeof logs> = {}
  for (const l of logs) {
    if (!logsByTask[l.taskId]) logsByTask[l.taskId] = []
    logsByTask[l.taskId].push(l)
  }
  const now = Date.now()
  return tasks.map(task => {
    const taskLogs = logsByTask[task.id] ?? []
    const lastRunState = state[task.id]?.lastRun ?? null
    const runs24h      = taskLogs.filter(l => l.message.includes('--- START ---')).length
    const completed24h = taskLogs.filter(l => l.message.includes('--- DONE')).length
    const errors24h    = taskLogs.filter(l => l.severity === 'error').length
    const warnings24h  = taskLogs.filter(l => l.severity === 'warning').length
    let nextRun: string | null = null
    if (lastRunState) {
      nextRun = new Date(new Date(lastRunState).getTime() + task.intervalSeconds * 1000).toISOString()
    }
    const recentLogs = taskLogs.slice(0, 10)
    const lastStart = recentLogs.find(l => l.message.includes('--- START ---'))
    const lastDone  = recentLogs.find(l => l.message.includes('--- DONE'))
    const hasRecentError = errors24h > 0 && taskLogs.slice(0, 5).some(l => l.severity === 'error')
    let status: AgentStatus = 'idle'
    if (hasRecentError) status = 'error'
    else if (lastStart && !lastDone) status = 'running'
    else if (!lastRunState || now - new Date(lastRunState).getTime() > task.intervalSeconds * 3000) status = 'offline'
    return {
      id: task.id,
      name: nameFromDesc(task.description),
      script: task.script,
      intervalSeconds: task.intervalSeconds,
      description: task.description,
      model: task.model,
      lastRun: lastRunState,
      nextRun,
      status,
      runs24h,
      completedRuns24h: completed24h,
      errors24h,
      warnings24h,
      avgRunMs: avgRunMs(metrics, task.id),
    }
  })
}

export function getQueueStats(): QueueStats {
  const raw = readQueue()
  const now = Date.now()
  const items: QueueItem[] = Object.entries(raw).map(([p, v]) => {
    const ingestedAt = v.ingestedAt ?? new Date(0).toISOString()
    const ageMs = now - new Date(ingestedAt).getTime()
    const agents = v.agents as Record<string, AgentSlotStatus>
    const hasPending = Object.values(agents).some(s => s === 'pending')
    return {
      path: p, ingestedAt, type: (v.type ?? 'other') as FileType, agents, ageMs,
      isStuck: hasPending && ageMs > 2 * 3600_000,
    }
  })
  const byType: Record<FileType, number> = { image: 0, document: 0, other: 0 }
  items.forEach(i => { byType[i.type] = (byType[i.type] ?? 0) + 1 })
  const pending = items.filter(i => Object.values(i.agents).some(s => s === 'pending')).length
  const done    = items.filter(i => Object.values(i.agents).every(s => s === 'done' || s === 'skip')).length
  const stuck   = items.filter(i => i.isStuck).length
  return {
    total: items.length, byType, byStatus: { pending, done, stuck },
    items: items.sort((a, b) => new Date(b.ingestedAt).getTime() - new Date(a.ingestedAt).getTime()),
  }
}

export function getPipelineStats(): PipelineStats {
  const processingDir  = path.join(VAULT_ROOT, '01-Processing')
  const processingFiles = scanDirectory(processingDir)
  const pendingReview = processingFiles.filter(f => !f.fm.reviewed || f.fm.status === 'draft').length
  const processedImages = readJson<{ images?: Record<string, { status?: string }> }>('processed-images.json', {})
  const classifiedImages = Object.values(processedImages.images ?? {}).filter(v => v?.status === 'ok').length
  const processedNpcs = readJson<{ npcs?: Record<string, { status?: string }> }>('processed-npcs.json', {})
  const generatedNpcs = Object.values(processedNpcs.npcs ?? {}).filter(v => v?.status === 'ok').length
  const logs24h = parseLogSince(24)
  const flow24h = logs24h.filter(l =>
    l.message.includes('--- DONE') || l.message.includes('Created') || l.message.includes('Wrote')
  ).length
  return {
    stages: [
      { id: 'inbox',      name: '00-Inbox',      folder: '00-Inbox',      count: countAllFiles(path.join(VAULT_ROOT, '00-Inbox')),   icon: '📥', color: '#6b7280' },
      { id: 'processing', name: '01-Processing',  folder: '01-Processing', count: countFiles(path.join(VAULT_ROOT, '01-Processing')), icon: '⚙️', color: '#0C5CAB' },
      { id: 'review',     name: 'Pending Review', folder: '01-Processing', count: pendingReview,                                      icon: '👁️', color: '#f59e0b' },
      { id: 'library',    name: '02-Library',     folder: '02-Library',    count: countFiles(path.join(VAULT_ROOT, '02-Library')),    icon: '📚', color: '#10b981' },
      { id: 'campaigns',  name: '03-Campaigns',   folder: '03-Campaigns',  count: countFiles(path.join(VAULT_ROOT, '03-Campaigns')),  icon: '⚔️', color: '#8b5cf6' },
    ],
    inboxImages: classifiedImages,
    processedItems: processingFiles.length,
    libraryEntities: countFiles(path.join(VAULT_ROOT, '02-Library')),
    pendingReview,
    totalFlow24h: flow24h,
  }
}

function findSourceImage(sources: string[]): string | null {
  if (!sources.length) return null
  const imgDir = path.join(VAULT_ROOT, '00-Inbox', 'images')
  // Strip extension from sources for partial matching (old drafts omit extension)
  const sourceBases = sources.map(s => String(s).replace(/\.[^.]+$/, ''))
  function walk(dir: string): string | null {
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name)
        if (e.isDirectory()) { const f = walk(full); if (f) return f }
        else if (
          sources.includes(e.name) ||
          sourceBases.some(b => e.name === b || e.name.startsWith(b + '.'))
        ) return full.replace(VAULT_ROOT, '').replace(/\\/g, '/')
      }
    } catch { /* ignore */ }
    return null
  }
  return walk(imgDir)
}

// Returns token path (forward-slash, leading-slash) or null
function findTokenForImage(imgRelPath: string | null): string | null {
  if (!imgRelPath) return null
  try {
    const tokens = readJson<{ tokens?: Record<string, { token?: string }> }>('generated-tokens.json', {})
    const index = tokens.tokens ?? {}
    // Normalize imgRelPath: strip leading slash, convert to backslash
    const key = imgRelPath.replace(/^\//, '').replace(/\//g, '\\')
    const entry = index[key]
    if (!entry?.token) return null
    return '/' + entry.token.replace(/\\/g, '/')
  } catch { return null }
}

export function getReviewItems(): ReviewItem[] {
  const processingDir = path.join(VAULT_ROOT, '01-Processing')
  const files = scanDirectory(processingDir)
  const { bySha256, tokenBySha256 } = readImageIndices()

  const items: ReviewItem[] = files.map(({ path: relPath, fm }) => {
    const rels = Array.isArray(fm.relationships) ? fm.relationships : []
    const body = fm.body ?? ''
    const descMatch = body.match(/##\s+Description\s*\n+([\s\S]*?)(?=\n##|\n---|\z)/)
    const description = descMatch ? descMatch[1].trim().slice(0, 200) : ''
    const sha256 = typeof fm.sha256 === 'string' ? fm.sha256 : null
    return {
      path: relPath,
      filename: path.basename(relPath, '.md'),
      id: fm.id ?? path.basename(relPath, '.md'),
      sha256,
      type: fm.type ?? 'unknown',
      status: (fm.status ?? 'draft') as ReviewStatus,
      quality: fm.quality ?? 0,
      suggestedQuality: fm.suggestedQuality ?? null,
      tags: Array.isArray(fm.tags) ? fm.tags : [],
      source: Array.isArray(fm.source) ? fm.source.map(String).filter(Boolean) : (fm.source ? [String(fm.source)] : []),
      reviewed: fm.reviewed ?? false,
      relationships: rels,
      hasRelationships: rels.length > 0,
      isOrphan: rels.length === 0 && !body.includes('[['),
      createdAt: fm.created ?? '',
      updatedAt: fm.updated ?? '',
      description,
      imageUrl: null,
      tokenUrl: null,
      agentNotes: (fm.agent_notes && typeof fm.agent_notes === 'object') ? fm.agent_notes as Record<string, string> : {},
    }
  })

  // Attach image + token URLs via sha256 lookups (O(1)); fallback to filesystem walk
  items.forEach(item => {
    if (item.sha256 && bySha256[item.sha256]) {
      const imgRelPath = bySha256[item.sha256].path
      const fwdPath = '/' + imgRelPath.replace(/\\/g, '/')
      item.imageUrl = `/api/image?path=${encodeURIComponent(fwdPath)}`
      const tokenRelPath = tokenBySha256[item.sha256]
      if (tokenRelPath) item.tokenUrl = `/api/image?path=${encodeURIComponent('/' + tokenRelPath.replace(/\\/g, '/'))}`
    } else if (item.source.length > 0) {
      const imgPath = findSourceImage(item.source)
      item.imageUrl = imgPath ? `/api/image?path=${encodeURIComponent(imgPath)}` : null
      const tokenPath = findTokenForImage(imgPath)
      item.tokenUrl = tokenPath ? `/api/image?path=${encodeURIComponent(tokenPath)}` : null
    }
  })

  items.sort((a, b) => {
    if (a.reviewed !== b.reviewed) return a.reviewed ? 1 : -1
    return (b.suggestedQuality ?? 0) - (a.suggestedQuality ?? 0)
  })
  return items
}
