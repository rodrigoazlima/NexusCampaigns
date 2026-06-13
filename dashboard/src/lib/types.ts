// ── Agent ──────────────────────────────────────────────────────────────────

export type AgentStatus = 'idle' | 'running' | 'error' | 'offline'

export interface AgentInfo {
  id: string
  name: string
  script: string
  intervalSeconds: number
  description: string
  model?: string
  lastRun: string | null        // ISO
  nextRun: string | null        // ISO (computed)
  status: AgentStatus
  runs24h: number
  completedRuns24h: number
  errors24h: number
  warnings24h: number
  avgRunMs: number | null
}

// ── Queue ──────────────────────────────────────────────────────────────────

export type AgentSlotStatus = 'pending' | 'done' | 'skip' | 'error'
export type FileType = 'image' | 'document' | 'other'

export interface QueueItem {
  path: string                  // relative path from vault root
  ingestedAt: string            // ISO
  type: FileType
  agents: Record<string, AgentSlotStatus>
  ageMs: number                 // computed
  isStuck: boolean              // computed: pending > 2h
}

export interface QueueStats {
  total: number
  byType: Record<FileType, number>
  byStatus: { pending: number; done: number; stuck: number }
  items: QueueItem[]
}

// ── Pipeline ───────────────────────────────────────────────────────────────

export interface PipelineStage {
  id: string
  name: string
  folder: string
  count: number
  icon: string
  color: string
}

export interface PipelineStats {
  stages: PipelineStage[]
  inboxImages: number
  processedItems: number
  libraryEntities: number
  pendingReview: number
  totalFlow24h: number
}

// ── Review ─────────────────────────────────────────────────────────────────

export type ReviewStatus = 'draft' | 'review' | 'approved' | 'archived'

export interface ReviewItem {
  path: string
  filename: string
  id: string
  sha256: string | null
  type: string
  status: ReviewStatus
  quality: number
  suggestedQuality: number | null
  tags: string[]
  source: string[]
  reviewed: boolean
  relationships: string[]
  hasRelationships: boolean
  isOrphan: boolean
  createdAt: string
  updatedAt: string
  description: string
  imageUrl: string | null
  tokenUrl: string | null
  agentNotes: Record<string, string>
}

// ── Library ────────────────────────────────────────────────────────────────

export interface LibraryStats {
  total: number
  byType: Record<string, number>
  avgQuality: number
  recentlyAdded: Array<{ path: string; id: string; type: string; addedAt: string }>
  orphanCount: number
  missingMetadataCount: number
}

// ── Logs ───────────────────────────────────────────────────────────────────

export type LogSeverity = 'info' | 'warning' | 'error'

export interface LogLine {
  timestamp: string
  taskId: string
  message: string
  severity: LogSeverity
}

// ── Reports ────────────────────────────────────────────────────────────────

export interface DailyReport {
  date: string
  generatedAt: string
  periodStart: string
  periodEnd: string
  summary: {
    totalRuns: number
    totalErrors: number
    totalWarnings: number
    tasksWithErrors: string[]
  }
  tasks: Record<string, {
    runs: number
    completedRuns: number
    errors: Array<{ timestamp: string; message: string }>
    warnings: Array<{ timestamp: string; message: string }>
    firstRun: string
    lastRun: string
  }>
  vaultHealth?: {
    pendingReview: string[]
    orphans: string[]
    qualitySuggestions: Record<string, number>
  }
}

// ── Vault Stats ────────────────────────────────────────────────────────────

export interface VaultStats {
  folders: {
    inbox: number
    processing: number
    library: number
    campaigns: number
    assets: number
    archive: number
  }
  images: {
    total: number
    classified: number
    withTokens: number
  }
  npcs: {
    total: number
    approved: number
  }
  growth: Array<{ date: string; library: number; processing: number }>
}
