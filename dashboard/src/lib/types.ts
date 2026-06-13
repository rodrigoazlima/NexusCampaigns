export type AgentStatus = 'running' | 'idle' | 'error' | 'offline' | 'planned'

export interface AgentRun {
  startedAt: string
  finishedAt: string
  durationMs: number
  itemsProcessed: number
  itemsFailed: number
}

export interface AgentInfo {
  id: string
  name: string
  status: AgentStatus
  description: string
  intervalSeconds: number
  llm: string
  intelligence: string
  fallbackIntelligence: string | null
  lastRun: string | null
  nextRun: string | null
  totalRuns: number
  totalProcessed: number
  totalFailed: number
  avgDurationMs: number
  recentRuns: AgentRun[]
}

export interface QueueItem {
  path: string
  ingestedAt: string
  type: string
  agents: Record<string, string>
}

export interface QueueStats {
  total: number
  pending: number
  done: number
  stuck: number
  byType: Record<string, number>
  items: QueueItem[]
}

export interface ReviewItem {
  filename: string
  filepath: string
  id: string
  type: string
  status: string
  quality: number
  created: string
  updated: string
  tags: string[]
  source: string[]
  reviewed: boolean
  relationships: string[]
  excerpt: string
}

export interface PipelineStage {
  name: string
  folder: string
  count: number
  owner: string
  color: string
}

export interface PipelineData {
  stages: PipelineStage[]
  throughput24h: number
  pendingReview: number
  librarySize: number
}

export interface LogLine {
  timestamp: string
  task: string
  severity: 'INFO' | 'WARN' | 'ERROR' | 'DEBUG'
  message: string
}

export interface DailyReport {
  generatedAt: string
  date: string
  agentSummaries: Record<string, AgentReportSummary>
}

export interface AgentReportSummary {
  runs: number
  completedRuns: number
  errors: number
  warnings: number
  firstRun: string
  lastRun: string
}

export interface VaultStats {
  inbox: number
  processing: number
  library: number
  campaigns: number
  assets: number
  relationships: number
  totalImages: number
  totalNpcs: number
  totalTokens: number
}

export interface InboxImage {
  path: string
  filename: string
  type: 'image' | 'document' | 'other'
  ingestedAt: string
  agentSlots: Record<string, string>
  hasToken: boolean
  tokenPath: string | null
  isStuck: boolean
}

export interface TokenFile {
  path: string
  filename: string
  entityId: string | null
}

export interface GMChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  agent: string
}

// ---------------------------------------------------------------------------
// Agent configuration (agent.json schema)
// ---------------------------------------------------------------------------

export interface ClaudeApiConfig {
  model: string
  system_file?: string | null
  tools_module?: string | null
  prompt_file?: string | null
  history_file?: string | null
  max_tokens?: number
  temperature?: number
  timeout_seconds?: number
  max_tool_rounds?: number
  max_tokens_per_run?: number | null
}

export interface OpenAIApiConfig {
  base_url: string
  model: string
  prompt_file?: string | null
  system_file?: string | null
  max_tokens?: number
  temperature?: number
  timeout_seconds?: number
}

export interface GeminiApiConfig {
  model: string
  prompt_file?: string | null
  system_file?: string | null
  max_tokens?: number
  temperature?: number
  timeout_seconds?: number
}

export interface OpenRouterApiConfig {
  model: string
  prompt_file?: string | null
  system_file?: string | null
  max_tokens?: number
  temperature?: number
  timeout_seconds?: number
}

export interface CliConfig {
  command: string
  args?: string[]
  cwd?: 'project_root' | 'agent_dir'
  timeout_seconds?: number
  env?: Record<string, string>
}

export interface ClaudeCodeConfig {
  prompt_file?: string | null
  prompt?: string | null
  extra_args?: string[]
  cwd?: 'project_root' | 'agent_dir'
  timeout_seconds?: number
  env?: Record<string, string>
}

export interface CodexCliConfig {
  prompt_file?: string | null
  prompt?: string | null
  model?: string
  approval_mode?: 'suggest' | 'auto-edit' | 'full-auto'
  extra_args?: string[]
  cwd?: 'project_root' | 'agent_dir'
  timeout_seconds?: number
  env?: Record<string, string>
}

export interface LmStudioConfig {
  base_url?: string
  model?: string
  max_tokens?: number
  temperature?: number
  timeout_seconds?: number
  system_file?: string | null
  prompt_file?: string | null
}

export interface IntelligenceConfig {
  type: 'cli' | 'claude-api' | 'openai-api' | 'gemini-api' | 'openrouter-api' | 'claude-code' | 'codex-cli' | 'lm-studio'
  cli?: CliConfig
  claude_api?: ClaudeApiConfig
  openai_api?: OpenAIApiConfig
  gemini_api?: GeminiApiConfig
  openrouter_api?: OpenRouterApiConfig
  claude_code?: ClaudeCodeConfig
  codex_cli?: CodexCliConfig
  lm_studio?: LmStudioConfig
}

export type AgentCapability = 'vision' | 'text' | 'speech' | 'tool-call'

export interface TaskConfig {
  intervalSeconds: number
  description: string
  required_capabilities?: AgentCapability[]
  dispatch: IntelligenceConfig
  fallback_dispatch?: IntelligenceConfig
  signal_triggers?: string[]
  emits_signals?: string[]
}

export interface AgentConfig {
  cleanupDays?: number
  tasks: Record<string, TaskConfig>
}

export interface RuntimeConfig {
  intervalSec: number
  python: string
  projectRoot: string
}

export interface PromptFile {
  path: string       // relative to .agents/, e.g. "ingestion/prompts/prompt.md"
  agent: string      // first folder segment, e.g. "ingestion"
  filename: string   // e.g. "prompt.md"
  sizeBytes: number
  modifiedAt: string // ISO timestamp
}

export interface ImageClassification {
  type: string        // portrait | body | battlemap | scene | token
  ancestry: string
  char_class: string
  creature_type: string
  element: string
  environment: string
  description: string
  sha256: string
  isToken: boolean
}

export interface ItemDetail extends ReviewItem {
  imageClassification: ImageClassification | null
  tokenPath: string | null
  tokenEligible: boolean   // true when imageClassification.type is portrait or body
  activeAgents: AgentInfo[]
}

export interface TokenConfig {
  molduraPath: string
}
