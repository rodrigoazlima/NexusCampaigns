'use client'

import { useEffect, useState, useCallback } from 'react'
import { X, AlertTriangle, Loader2, CheckCircle } from 'lucide-react'
import type { AgentConfig, RuntimeConfig, IntelligenceConfig, AgentCapability } from '@/lib/types'

interface AgentConfigDialogProps {
  agentName: string
  agentDisplayName: string
  open: boolean
  onClose: () => void
}

type ConfigData = AgentConfig | RuntimeConfig

const TYPE_KEY_MAP: Record<string, keyof IntelligenceConfig> = {
  'cli': 'cli',
  'claude-api': 'claude_api',
  'openai-api': 'openai_api',
  'gemini-api': 'gemini_api',
  'openrouter-api': 'openrouter_api',
  'claude-code': 'claude_code',
  'codex-cli': 'codex_cli',
  'lm-studio': 'lm_studio',
}

const DEFAULT_INTELLIGENCE: Record<string, Record<string, unknown>> = {
  'cli': { command: '', args: [], cwd: 'project_root', timeout_seconds: 300, env: {} },
  'claude-api': { model: 'claude-haiku-4-5-20251001', max_tokens: 4096, temperature: 0.0, timeout_seconds: 120, max_tool_rounds: 20 },
  'openai-api': { base_url: '', model: '', max_tokens: 1024, temperature: 0.0, timeout_seconds: 120 },
  'gemini-api': { model: '', max_tokens: 2048, temperature: 0.0, timeout_seconds: 120 },
  'openrouter-api': { model: '', max_tokens: 4096, temperature: 0.0, timeout_seconds: 180 },
  'claude-code': { prompt_file: 'prompts/prompt.md', prompt: null, extra_args: ['--dangerously-skip-permissions'], cwd: 'project_root', timeout_seconds: 600, env: {} },
  'codex-cli': { prompt_file: 'prompts/prompt.md', prompt: null, model: 'o4-mini', approval_mode: 'full-auto', extra_args: [], cwd: 'project_root', timeout_seconds: 600, env: {} },
  'lm-studio': { base_url: 'http://localhost:1234/v1', model: '', max_tokens: 64000, temperature: 0.0, timeout_seconds: 1800, system_file: null, prompt_file: null },
}

// Capabilities each provider definitively supports (guaranteed)
const PROVIDER_CAPS_DEFINITE: Record<string, AgentCapability[]> = {
  'claude-api':     ['vision', 'text', 'tool-call'],
  'claude-code':    ['text', 'tool-call'],
  'codex-cli':      ['text', 'tool-call'],
  'openai-api':     ['text'],
  'gemini-api':     ['text', 'tool-call'],
  'openrouter-api': ['text'],
  'lm-studio':      ['text'],
  'cli':            [],
}

// Capabilities that may be available depending on the specific model chosen
const PROVIDER_CAPS_UNCERTAIN: Record<string, AgentCapability[]> = {
  'openai-api':     ['vision', 'tool-call'],
  'gemini-api':     ['vision'],
  'openrouter-api': ['vision', 'tool-call'],
  'lm-studio':      ['vision', 'tool-call'],
}

const CAPABILITY_LABELS: Record<AgentCapability, string> = {
  vision:      'Vision',
  text:        'Text',
  speech:      'Speech',
  'tool-call': 'Tool Call',
}

function intervalLabel(s: number): string {
  if (s >= 86400 && s % 86400 === 0) return `${s / 86400}d`
  if (s >= 3600 && s % 3600 === 0) return `${s / 3600}h`
  if (s >= 60 && s % 60 === 0) return `${s / 60}m`
  return `${s}s`
}

function isRuntimeConfig(data: ConfigData): data is RuntimeConfig {
  return 'intervalSec' in data
}

// ---------------------------------------------------------------------------
// Field helpers
// ---------------------------------------------------------------------------

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <label className="w-40 shrink-0 text-xs text-zinc-500 pt-2 leading-none">{label}</label>
      <div className="flex-1">{children}</div>
    </div>
  )
}

function TextInput({
  value, onChange, placeholder, mono,
}: { value: string; onChange: (v: string) => void; placeholder?: string; mono?: boolean }) {
  return (
    <input
      type="text"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-primary/60 ${mono ? 'font-mono' : ''}`}
    />
  )
}

function NumberInput({
  value, onChange, min, max, step,
}: { value: number | undefined; onChange: (v: number) => void; min?: number; max?: number; step?: number }) {
  return (
    <input
      type="number"
      value={value ?? ''}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      min={min}
      max={max}
      step={step ?? 1}
      className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-primary/60"
    />
  )
}

function SelectInput({
  value, onChange, options,
}: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-primary/60"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}

function TemperatureField({ value, onChange }: { value: number | undefined; onChange: (v: number) => void }) {
  const val = value ?? 0
  return (
    <div className="flex items-center gap-2">
      <input
        type="range"
        min={0} max={1} step={0.01}
        value={val}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="flex-1 accent-primary h-1"
      />
      <span className="text-xs font-mono text-zinc-300 w-8 text-right">{val.toFixed(2)}</span>
    </div>
  )
}

function TagList({ tags, label }: { tags: string[]; label: string }) {
  if (!tags || tags.length === 0) return null
  return (
    <FieldRow label={label}>
      <div className="flex flex-wrap gap-1">
        {tags.map((t) => (
          <span key={t} className="px-1.5 py-0.5 bg-primary/10 border border-primary/20 rounded text-[10px] font-mono text-primary">{t}</span>
        ))}
      </div>
    </FieldRow>
  )
}

function TextareaInput({ value, onChange, rows, mono }: { value: string; onChange: (v: string) => void; rows?: number; mono?: boolean }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      rows={rows ?? 3}
      className={`w-full bg-surface-2 border border-surface-3 rounded px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-primary/60 resize-y ${mono ? 'font-mono' : ''}`}
    />
  )
}

// ---------------------------------------------------------------------------
// Dispatch field groups
// ---------------------------------------------------------------------------

function ClaudeApiFields({
  cfg, onChange,
}: {
  cfg: Record<string, unknown>
  onChange: (field: string, value: unknown) => void
}) {
  return (
    <div className="space-y-3">
      <FieldRow label="Model">
        <TextInput value={cfg.model as string} onChange={(v) => onChange('model', v)} mono />
      </FieldRow>
      <FieldRow label="Max Tokens">
        <NumberInput value={cfg.max_tokens as number} onChange={(v) => onChange('max_tokens', v)} min={1} />
      </FieldRow>
      <FieldRow label="Temperature">
        <TemperatureField value={cfg.temperature as number} onChange={(v) => onChange('temperature', v)} />
      </FieldRow>
      <FieldRow label="Timeout (s)">
        <NumberInput value={cfg.timeout_seconds as number} onChange={(v) => onChange('timeout_seconds', v)} min={1} />
      </FieldRow>
      <FieldRow label="Max Tool Rounds">
        <NumberInput value={cfg.max_tool_rounds as number} onChange={(v) => onChange('max_tool_rounds', v)} min={1} />
      </FieldRow>
      <FieldRow label="Max Tokens/Run">
        <NumberInput
          value={cfg.max_tokens_per_run as number | undefined}
          onChange={(v) => onChange('max_tokens_per_run', isNaN(v) ? null : v)}
          min={0}
        />
        <p className="text-[10px] text-zinc-600 mt-1">Leave empty for no limit</p>
      </FieldRow>
      <FieldRow label="System File">
        <TextInput value={(cfg.system_file as string) ?? ''} onChange={(v) => onChange('system_file', v || null)} placeholder="prompts/system.md" mono />
      </FieldRow>
      <FieldRow label="Tools Module">
        <TextInput value={(cfg.tools_module as string) ?? ''} onChange={(v) => onChange('tools_module', v || null)} placeholder="agent.tools.module_name" mono />
      </FieldRow>
      <FieldRow label="Prompt File">
        <TextInput value={(cfg.prompt_file as string) ?? ''} onChange={(v) => onChange('prompt_file', v || null)} placeholder="prompts/prompt.md" mono />
      </FieldRow>
      <FieldRow label="History File">
        <TextInput value={(cfg.history_file as string) ?? ''} onChange={(v) => onChange('history_file', v || null)} placeholder="history.json" mono />
      </FieldRow>
    </div>
  )
}

function OpenAIApiFields({ cfg, onChange }: { cfg: Record<string, unknown>; onChange: (field: string, value: unknown) => void }) {
  return (
    <div className="space-y-3">
      <FieldRow label="Base URL">
        <TextInput value={cfg.base_url as string} onChange={(v) => onChange('base_url', v)} mono />
      </FieldRow>
      <FieldRow label="Model">
        <TextInput value={cfg.model as string} onChange={(v) => onChange('model', v)} mono />
      </FieldRow>
      <FieldRow label="Max Tokens">
        <NumberInput value={cfg.max_tokens as number} onChange={(v) => onChange('max_tokens', v)} min={1} />
      </FieldRow>
      <FieldRow label="Temperature">
        <TemperatureField value={cfg.temperature as number} onChange={(v) => onChange('temperature', v)} />
      </FieldRow>
      <FieldRow label="Timeout (s)">
        <NumberInput value={cfg.timeout_seconds as number} onChange={(v) => onChange('timeout_seconds', v)} min={1} />
      </FieldRow>
      <FieldRow label="System File">
        <TextInput value={(cfg.system_file as string) ?? ''} onChange={(v) => onChange('system_file', v || null)} mono />
      </FieldRow>
      <FieldRow label="Prompt File">
        <TextInput value={(cfg.prompt_file as string) ?? ''} onChange={(v) => onChange('prompt_file', v || null)} mono />
      </FieldRow>
    </div>
  )
}

function GeminiOrOpenRouterFields({ cfg, onChange }: { cfg: Record<string, unknown>; onChange: (field: string, value: unknown) => void }) {
  return (
    <div className="space-y-3">
      <FieldRow label="Model">
        <TextInput value={cfg.model as string} onChange={(v) => onChange('model', v)} mono />
      </FieldRow>
      <FieldRow label="Max Tokens">
        <NumberInput value={cfg.max_tokens as number} onChange={(v) => onChange('max_tokens', v)} min={1} />
      </FieldRow>
      <FieldRow label="Temperature">
        <TemperatureField value={cfg.temperature as number} onChange={(v) => onChange('temperature', v)} />
      </FieldRow>
      <FieldRow label="Timeout (s)">
        <NumberInput value={cfg.timeout_seconds as number} onChange={(v) => onChange('timeout_seconds', v)} min={1} />
      </FieldRow>
      <FieldRow label="System File">
        <TextInput value={(cfg.system_file as string) ?? ''} onChange={(v) => onChange('system_file', v || null)} mono />
      </FieldRow>
      <FieldRow label="Prompt File">
        <TextInput value={(cfg.prompt_file as string) ?? ''} onChange={(v) => onChange('prompt_file', v || null)} mono />
      </FieldRow>
    </div>
  )
}

function CliFields({ cfg, onChange }: { cfg: Record<string, unknown>; onChange: (field: string, value: unknown) => void }) {
  const argsText = Array.isArray(cfg.args) ? (cfg.args as string[]).join('\n') : ''
  const envText = cfg.env ? JSON.stringify(cfg.env, null, 2) : '{}'

  return (
    <div className="space-y-3">
      <FieldRow label="Command">
        <TextInput value={cfg.command as string} onChange={(v) => onChange('command', v)} mono />
      </FieldRow>
      <FieldRow label="Args">
        <TextareaInput
          value={argsText}
          onChange={(v) => onChange('args', v.split('\n').filter(Boolean))}
          rows={3}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">One arg per line</p>
      </FieldRow>
      <FieldRow label="CWD">
        <SelectInput
          value={(cfg.cwd as string) ?? 'project_root'}
          onChange={(v) => onChange('cwd', v)}
          options={[
            { value: 'project_root', label: 'Project Root' },
            { value: 'agent_dir', label: 'Agent Dir' },
          ]}
        />
      </FieldRow>
      <FieldRow label="Timeout (s)">
        <NumberInput value={cfg.timeout_seconds as number} onChange={(v) => onChange('timeout_seconds', v)} min={1} />
      </FieldRow>
      <FieldRow label="Env Vars">
        <TextareaInput
          value={envText}
          onChange={(v) => {
            try { onChange('env', JSON.parse(v)) } catch { /* ignore invalid JSON */ }
          }}
          rows={4}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">JSON object of env vars</p>
      </FieldRow>
    </div>
  )
}

function ClaudeCodeFields({ cfg, onChange }: { cfg: Record<string, unknown>; onChange: (field: string, value: unknown) => void }) {
  const extraArgsText = Array.isArray(cfg.extra_args) ? (cfg.extra_args as string[]).join('\n') : '--dangerously-skip-permissions'
  const envText = cfg.env ? JSON.stringify(cfg.env, null, 2) : '{}'

  return (
    <div className="space-y-3">
      <FieldRow label="Prompt File">
        <TextInput
          value={(cfg.prompt_file as string) ?? ''}
          onChange={(v) => onChange('prompt_file', v || null)}
          placeholder="prompts/prompt.md"
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">Path relative to agent dir; supports {'{{project_root}}'} placeholders</p>
      </FieldRow>
      <FieldRow label="Inline Prompt">
        <TextareaInput
          value={(cfg.prompt as string) ?? ''}
          onChange={(v) => onChange('prompt', v || null)}
          rows={4}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">Used only when prompt_file is empty</p>
      </FieldRow>
      <FieldRow label="Extra Args">
        <TextareaInput
          value={extraArgsText}
          onChange={(v) => onChange('extra_args', v.split('\n').filter(Boolean))}
          rows={3}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">One arg per line — include --dangerously-skip-permissions to bypass permission prompts</p>
      </FieldRow>
      <FieldRow label="CWD">
        <SelectInput
          value={(cfg.cwd as string) ?? 'project_root'}
          onChange={(v) => onChange('cwd', v)}
          options={[
            { value: 'project_root', label: 'Project Root' },
            { value: 'agent_dir', label: 'Agent Dir' },
          ]}
        />
      </FieldRow>
      <FieldRow label="Timeout (s)">
        <NumberInput value={cfg.timeout_seconds as number} onChange={(v) => onChange('timeout_seconds', v)} min={1} />
      </FieldRow>
      <FieldRow label="Env Vars">
        <TextareaInput
          value={envText}
          onChange={(v) => {
            try { onChange('env', JSON.parse(v)) } catch { /* ignore invalid JSON */ }
          }}
          rows={3}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">JSON object of env vars</p>
      </FieldRow>
    </div>
  )
}

function CodexCliFields({ cfg, onChange }: { cfg: Record<string, unknown>; onChange: (field: string, value: unknown) => void }) {
  const extraArgsText = Array.isArray(cfg.extra_args) ? (cfg.extra_args as string[]).join('\n') : ''
  const envText = cfg.env ? JSON.stringify(cfg.env, null, 2) : '{}'

  return (
    <div className="space-y-3">
      <FieldRow label="Prompt File">
        <TextInput
          value={(cfg.prompt_file as string) ?? ''}
          onChange={(v) => onChange('prompt_file', v || null)}
          placeholder="prompts/prompt.md"
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">Path relative to agent dir</p>
      </FieldRow>
      <FieldRow label="Inline Prompt">
        <TextareaInput
          value={(cfg.prompt as string) ?? ''}
          onChange={(v) => onChange('prompt', v || null)}
          rows={4}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">Used only when prompt_file is empty</p>
      </FieldRow>
      <FieldRow label="Model">
        <TextInput
          value={(cfg.model as string) ?? 'o4-mini'}
          onChange={(v) => onChange('model', v)}
          placeholder="o4-mini"
          mono
        />
      </FieldRow>
      <FieldRow label="Approval Mode">
        <SelectInput
          value={(cfg.approval_mode as string) ?? 'full-auto'}
          onChange={(v) => onChange('approval_mode', v)}
          options={[
            { value: 'suggest', label: 'Suggest' },
            { value: 'auto-edit', label: 'Auto Edit' },
            { value: 'full-auto', label: 'Full Auto' },
          ]}
        />
      </FieldRow>
      <FieldRow label="Extra Args">
        <TextareaInput
          value={extraArgsText}
          onChange={(v) => onChange('extra_args', v.split('\n').filter(Boolean))}
          rows={3}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">One arg per line</p>
      </FieldRow>
      <FieldRow label="CWD">
        <SelectInput
          value={(cfg.cwd as string) ?? 'project_root'}
          onChange={(v) => onChange('cwd', v)}
          options={[
            { value: 'project_root', label: 'Project Root' },
            { value: 'agent_dir', label: 'Agent Dir' },
          ]}
        />
      </FieldRow>
      <FieldRow label="Timeout (s)">
        <NumberInput value={cfg.timeout_seconds as number} onChange={(v) => onChange('timeout_seconds', v)} min={1} />
      </FieldRow>
      <FieldRow label="Env Vars">
        <TextareaInput
          value={envText}
          onChange={(v) => {
            try { onChange('env', JSON.parse(v)) } catch { /* ignore invalid JSON */ }
          }}
          rows={3}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">JSON object of env vars</p>
      </FieldRow>
    </div>
  )
}

function LmStudioFields({ cfg, onChange }: { cfg: Record<string, unknown>; onChange: (field: string, value: unknown) => void }) {
  const [models, setModels] = useState<string[]>([])
  const [fetchStatus, setFetchStatus] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const baseUrl = (cfg.base_url as string) || 'http://localhost:1234/v1'

  const fetchModels = useCallback(() => {
    setFetchStatus('loading')
    fetch(`/api/lm-studio/models?baseUrl=${encodeURIComponent(baseUrl)}`)
      .then(r => r.json())
      .then((d: { data?: { id: string }[] }) => {
        const ids = (d.data ?? []).map(m => m.id)
        setModels(ids)
        setFetchStatus(ids.length > 0 ? 'ok' : 'error')
      })
      .catch(() => {
        setModels([])
        setFetchStatus('error')
      })
  }, [baseUrl])

  useEffect(() => { fetchModels() }, [])

  const currentModel = (cfg.model as string) ?? ''
  const modelOptions = models.includes(currentModel) || !currentModel
    ? models
    : [currentModel, ...models]

  return (
    <div className="space-y-3">
      <FieldRow label="Base URL">
        <TextInput value={baseUrl} onChange={(v) => onChange('base_url', v)} mono />
      </FieldRow>
      <FieldRow label="Model">
        <div className="flex gap-2">
          {fetchStatus === 'ok' && modelOptions.length > 0 ? (
            <div className="flex-1">
              <SelectInput
                value={currentModel}
                onChange={(v) => onChange('model', v)}
                options={modelOptions.map(m => ({ value: m, label: m }))}
              />
            </div>
          ) : (
            <div className="flex-1">
              <TextInput value={currentModel} onChange={(v) => onChange('model', v)} mono placeholder="model-id" />
            </div>
          )}
          <button
            onClick={fetchModels}
            disabled={fetchStatus === 'loading'}
            className="shrink-0 px-2 py-1 text-[11px] bg-surface-2 border border-surface-3 rounded hover:border-primary/60 text-zinc-400 hover:text-zinc-200 disabled:opacity-40 transition-colors"
            title="Refresh models"
          >
            {fetchStatus === 'loading' ? '…' : '↻'}
          </button>
        </div>
        {fetchStatus === 'error' && <p className="text-[10px] text-red-500/70 mt-1">LM Studio not reachable — enter model ID manually</p>}
      </FieldRow>
      <FieldRow label="Max Tokens">
        <NumberInput value={cfg.max_tokens as number} onChange={(v) => onChange('max_tokens', v)} min={1} />
      </FieldRow>
      <FieldRow label="Temperature">
        <TemperatureField value={cfg.temperature as number} onChange={(v) => onChange('temperature', v)} />
      </FieldRow>
      <FieldRow label="Timeout (s)">
        <NumberInput value={cfg.timeout_seconds as number} onChange={(v) => onChange('timeout_seconds', v)} min={1} />
        <p className="text-[10px] text-zinc-600 mt-1">= {intervalLabel(cfg.timeout_seconds as number)}</p>
      </FieldRow>
      <FieldRow label="System File">
        <TextInput value={(cfg.system_file as string) ?? ''} onChange={(v) => onChange('system_file', v || null)} mono />
      </FieldRow>
      <FieldRow label="Prompt File">
        <TextInput value={(cfg.prompt_file as string) ?? ''} onChange={(v) => onChange('prompt_file', v || null)} mono />
      </FieldRow>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main dialog
// ---------------------------------------------------------------------------

export default function AgentConfigDialog({
  agentName, agentDisplayName, open, onClose,
}: AgentConfigDialogProps) {
  const [config, setConfig] = useState<ConfigData | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    setConfig(null)
    setFetchError(null)
    setSaveStatus('idle')
    setLoading(true)
    fetch(`/api/config/${agentName}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 404 ? 'No configuration file found for this agent.' : `HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => setConfig(data))
      .catch((e) => setFetchError(e.message))
      .finally(() => setLoading(false))
  }, [open, agentName])

  const handleSave = useCallback(async () => {
    if (!config) return
    setSaving(true)
    setSaveStatus('idle')
    setSaveError(null)
    try {
      const res = await fetch(`/api/config/${agentName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (!res.ok) throw new Error(`Save failed: HTTP ${res.status}`)
      setSaveStatus('success')
      setTimeout(() => onClose(), 800)
    } catch (e) {
      setSaveStatus('error')
      setSaveError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }, [agentName, config])

  const updateTask = useCallback((taskId: string, field: string, value: unknown) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      ;(next.tasks[taskId] as unknown as Record<string, unknown>)[field] = value
      return next
    })
  }, [])

  const updateIntelligenceField = useCallback((taskId: string, field: string, value: unknown) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      const intelligence = next.tasks[taskId].dispatch
      const key = TYPE_KEY_MAP[intelligence.type]
      if (key && intelligence[key]) {
        (intelligence[key] as unknown as Record<string, unknown>)[field] = value
      }
      return next
    })
  }, [])

  const updateIntelligenceType = useCallback((taskId: string, newType: string) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      const task = next.tasks[taskId]
      const oldKey = TYPE_KEY_MAP[task.dispatch.type]
      const newKey = TYPE_KEY_MAP[newType]
      if (oldKey) delete task.dispatch[oldKey]
      task.dispatch.type = newType as IntelligenceConfig['type']
      if (newKey) {
        task.dispatch[newKey] = { ...(DEFAULT_INTELLIGENCE[newType] ?? {}) } as never
      }
      return next
    })
  }, [])

  const updateFallbackField = useCallback((taskId: string, field: string, value: unknown) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      const fb = next.tasks[taskId].fallback_dispatch
      if (!fb) return prev
      const key = TYPE_KEY_MAP[fb.type]
      if (key && fb[key]) {
        (fb[key] as unknown as Record<string, unknown>)[field] = value
      }
      return next
    })
  }, [])

  const updateFallbackType = useCallback((taskId: string, newType: string) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      const task = next.tasks[taskId]
      if (!task.fallback_dispatch) return prev
      const oldKey = TYPE_KEY_MAP[task.fallback_dispatch.type]
      const newKey = TYPE_KEY_MAP[newType]
      if (oldKey) delete task.fallback_dispatch[oldKey]
      task.fallback_dispatch.type = newType as IntelligenceConfig['type']
      if (newKey) {
        task.fallback_dispatch[newKey] = { ...(DEFAULT_INTELLIGENCE[newType] ?? {}) } as never
      }
      return next
    })
  }, [])

  const toggleFallback = useCallback((taskId: string, enabled: boolean) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      if (enabled) {
        next.tasks[taskId].fallback_dispatch = {
          type: 'cli',
          cli: { ...(DEFAULT_INTELLIGENCE['cli'] ?? {}) } as never,
        }
      } else {
        delete next.tasks[taskId].fallback_dispatch
      }
      return next
    })
  }, [])

  const updateTopLevel = useCallback((field: string, value: unknown) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      return { ...prev, [field]: value }
    })
  }, [])

  const updateRuntime = useCallback((field: string, value: unknown) => {
    setConfig((prev) => {
      if (!prev || !isRuntimeConfig(prev)) return prev
      return { ...prev, [field]: value }
    })
  }, [])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={onClose} />

      <div className="relative z-10 w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col bg-surface-1 border border-surface-3 rounded-xl shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-3 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-zinc-100">Configure: {agentDisplayName}</h2>
            <p className="text-xs text-zinc-500 mt-0.5 font-mono">{agentName}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-surface-2 text-zinc-400 hover:text-zinc-200 transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-12 gap-2 text-zinc-500">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-xs">Loading configuration…</span>
            </div>
          )}

          {fetchError && (
            <div className="flex items-start gap-2 py-6 text-zinc-400">
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" />
              <span className="text-xs">{fetchError}</span>
            </div>
          )}

          {config && !loading && (
            <div className="space-y-6">
              {isRuntimeConfig(config) ? (
                <RuntimeForm config={config} onChange={updateRuntime} />
              ) : (
                <AgentForm
                  agentName={agentName}
                  config={config}
                  onTopLevelChange={updateTopLevel}
                  onTaskChange={updateTask}
                  onIntelligenceChange={updateIntelligenceField}
                  onIntelligenceTypeChange={updateIntelligenceType}
                  onFallbackChange={updateFallbackField}
                  onFallbackTypeChange={updateFallbackType}
                  onFallbackToggle={toggleFallback}
                />
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {config && !loading && !fetchError && (
          <div className="shrink-0 flex items-center justify-between px-5 py-3 border-t border-surface-3">
            <div className="flex items-center gap-2">
              {saveStatus === 'success' && (
                <span className="flex items-center gap-1 text-xs text-success">
                  <CheckCircle size={12} /> Saved
                </span>
              )}
              {saveStatus === 'error' && (
                <span className="text-xs text-danger">{saveError}</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-1.5 text-xs font-medium bg-primary hover:bg-primary/80 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded transition-colors flex items-center gap-1.5"
              >
                {saving && <Loader2 size={11} className="animate-spin" />}
                {saving ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Runtime form
// ---------------------------------------------------------------------------

function RuntimeForm({ config, onChange }: { config: RuntimeConfig; onChange: (field: string, value: unknown) => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 p-3 bg-warning/5 border border-warning/20 rounded-lg">
        <AlertTriangle size={13} className="text-warning mt-0.5 shrink-0" />
        <p className="text-xs text-warning/80">Changes require a daemon restart to take effect.</p>
      </div>
      <div className="space-y-3">
        <FieldRow label="Poll Interval (s)">
          <NumberInput value={config.intervalSec} onChange={(v) => onChange('intervalSec', v)} min={10} />
          <p className="text-[10px] text-zinc-600 mt-1">How often the daemon calls runner.py — {intervalLabel(config.intervalSec)}</p>
        </FieldRow>
        <FieldRow label="Python Executable">
          <TextInput value={config.python} onChange={(v) => onChange('python', v)} mono />
        </FieldRow>
        <FieldRow label="Project Root">
          <TextInput value={config.projectRoot} onChange={(v) => onChange('projectRoot', v)} mono />
        </FieldRow>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab primitives
// ---------------------------------------------------------------------------

interface TabDef { id: string; label: string; badge?: string }

function Tabs({ tabs, active, onChange }: {
  tabs: TabDef[]
  active: string
  onChange: (id: string) => void
}) {
  return (
    <div className="flex border-b border-surface-3 mb-4 gap-0">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
            active === tab.id
              ? 'text-zinc-100 border-primary'
              : 'text-zinc-500 border-transparent hover:text-zinc-300 hover:border-surface-3'
          }`}
        >
          {tab.label}
          {tab.badge && (
            <span className={`text-[9px] px-1 py-0.5 rounded font-mono ${
              active === tab.id ? 'bg-primary/20 text-primary' : 'bg-surface-3 text-zinc-500'
            }`}>{tab.badge}</span>
          )}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dispatch helpers (shared by Dispatch + Fallback tabs)
// ---------------------------------------------------------------------------

const DISPATCH_OPTIONS = [
  { value: 'claude-api', label: 'Claude API' },
  { value: 'claude-code', label: 'Claude Code CLI' },
  { value: 'codex-cli', label: 'Codex CLI' },
  { value: 'lm-studio', label: 'LM Studio' },
  { value: 'openai-api', label: 'OpenAI API' },
  { value: 'gemini-api', label: 'Gemini API' },
  { value: 'openrouter-api', label: 'OpenRouter API' },
  { value: 'cli', label: 'CLI' },
]

function CapabilityWarnings({ providerType, required }: { providerType: string; required: AgentCapability[] }) {
  if (!required || required.length === 0) return null
  const definite = PROVIDER_CAPS_DEFINITE[providerType] ?? []
  const uncertain = PROVIDER_CAPS_UNCERTAIN[providerType] ?? []
  const missing = required.filter(c => !definite.includes(c))
  const warnings = missing.map(c => ({
    cap: c,
    uncertain: uncertain.includes(c),
  }))
  if (warnings.length === 0) return null
  return (
    <div className="space-y-1.5 mb-3">
      {warnings.map(({ cap, uncertain }) => (
        <div
          key={cap}
          role="alert"
          className={`flex items-start gap-2 rounded px-2.5 py-2 text-[11px] border ${
            uncertain
              ? 'bg-yellow-500/5 border-yellow-500/20 text-yellow-400/80'
              : 'bg-red-500/8 border-red-500/20 text-red-400/80'
          }`}
        >
          <span aria-label={uncertain ? 'Warning' : 'Error'} className="mt-px shrink-0">
            {uncertain ? '⚠' : '✕'}
          </span>
          <span>
            <span className="font-semibold">{CAPABILITY_LABELS[cap]}</span>
            {uncertain
              ? ` support depends on the specific model loaded — verify before use.`
              : ` is required but not supported by this provider.`}
          </span>
        </div>
      ))}
    </div>
  )
}

function IntelligenceFields({ intelligence, onChange, requiredCapabilities }: {
  intelligence: IntelligenceConfig
  onChange: (field: string, value: unknown) => void
  requiredCapabilities?: AgentCapability[]
}) {
  const key = TYPE_KEY_MAP[intelligence.type]
  const cfg = (key ? intelligence[key] : null) as Record<string, unknown> | null
  const warnings = <CapabilityWarnings providerType={intelligence.type} required={requiredCapabilities ?? []} />
  if (!cfg) return warnings
  const fields = (() => {
    if (intelligence.type === 'claude-api') return <ClaudeApiFields cfg={cfg} onChange={onChange} />
    if (intelligence.type === 'openai-api') return <OpenAIApiFields cfg={cfg} onChange={onChange} />
    if (intelligence.type === 'gemini-api' || intelligence.type === 'openrouter-api') return <GeminiOrOpenRouterFields cfg={cfg} onChange={onChange} />
    if (intelligence.type === 'cli') return <CliFields cfg={cfg} onChange={onChange} />
    if (intelligence.type === 'claude-code') return <ClaudeCodeFields cfg={cfg} onChange={onChange} />
    if (intelligence.type === 'codex-cli') return <CodexCliFields cfg={cfg} onChange={onChange} />
    if (intelligence.type === 'lm-studio') return <LmStudioFields cfg={cfg} onChange={onChange} />
    return null
  })()
  return <>{warnings}{fields}</>
}

// ---------------------------------------------------------------------------
// Agent form — tabs per task when multiple tasks exist
// ---------------------------------------------------------------------------

function AgentForm({
  agentName, config, onTopLevelChange, onTaskChange, onIntelligenceChange, onIntelligenceTypeChange,
  onFallbackChange, onFallbackTypeChange, onFallbackToggle,
}: {
  agentName: string
  config: AgentConfig
  onTopLevelChange: (field: string, value: unknown) => void
  onTaskChange: (taskId: string, field: string, value: unknown) => void
  onIntelligenceChange: (taskId: string, field: string, value: unknown) => void
  onIntelligenceTypeChange: (taskId: string, newType: string) => void
  onFallbackChange: (taskId: string, field: string, value: unknown) => void
  onFallbackTypeChange: (taskId: string, newType: string) => void
  onFallbackToggle: (taskId: string, enabled: boolean) => void
}) {
  const taskEntries = Object.entries(config.tasks)
  const [activeTask, setActiveTask] = useState(taskEntries[0]?.[0] ?? '')

  const taskTabs: TabDef[] = taskEntries.map(([id]) => ({ id, label: id }))
  const activeEntry = taskEntries.find(([id]) => id === activeTask)

  return (
    <div className="space-y-4">
      {config.cleanupDays !== undefined && (
        <FieldRow label="Cleanup Days">
          <NumberInput value={config.cleanupDays} onChange={(v) => onTopLevelChange('cleanupDays', v)} min={1} />
        </FieldRow>
      )}

      {taskEntries.length > 1 && (
        <Tabs tabs={taskTabs} active={activeTask} onChange={setActiveTask} />
      )}

      {activeEntry && (
        <TaskForm
          agentName={agentName}
          taskId={activeEntry[0]}
          task={activeEntry[1]}
          onTaskChange={onTaskChange}
          onIntelligenceChange={onIntelligenceChange}
          onIntelligenceTypeChange={onIntelligenceTypeChange}
          onFallbackChange={onFallbackChange}
          onFallbackTypeChange={onFallbackTypeChange}
          onFallbackToggle={onFallbackToggle}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Task form — tabs: General | Dispatch | Fallback
// ---------------------------------------------------------------------------

function getIntelligencePromptFile(intelligence: IntelligenceConfig): string | null {
  if (intelligence.type === 'claude-code') return (intelligence.claude_code as Record<string, unknown> | undefined)?.prompt_file as string ?? null
  if (intelligence.type === 'claude-api') {
    const c = intelligence.claude_api as Record<string, unknown> | undefined
    return (c?.prompt_file ?? c?.system_file) as string ?? null
  }
  return null
}

function TaskForm({
  agentName, taskId, task, onTaskChange, onIntelligenceChange, onIntelligenceTypeChange,
  onFallbackChange, onFallbackTypeChange, onFallbackToggle,
}: {
  agentName: string
  taskId: string
  task: import('@/lib/types').TaskConfig
  onTaskChange: (taskId: string, field: string, value: unknown) => void
  onIntelligenceChange: (taskId: string, field: string, value: unknown) => void
  onIntelligenceTypeChange: (taskId: string, newType: string) => void
  onFallbackChange: (taskId: string, field: string, value: unknown) => void
  onFallbackTypeChange: (taskId: string, newType: string) => void
  onFallbackToggle: (taskId: string, enabled: boolean) => void
}) {
  const [activeTab, setActiveTab] = useState<'general' | 'intelligence' | 'fallback'>('general')
  const fb = task.fallback_dispatch

  const tabs: TabDef[] = [
    { id: 'general', label: 'General' },
    { id: 'intelligence', label: 'Intelligence', badge: task.dispatch.type },
    { id: 'fallback', label: 'Fallback', badge: fb ? fb.type : undefined },
  ]

  return (
    <div>
      <Tabs tabs={tabs} active={activeTab} onChange={(id) => setActiveTab(id as typeof activeTab)} />

      {activeTab === 'general' && (
        <div className="space-y-3">
          <FieldRow label="Description">
            <TextInput value={task.description} onChange={(v) => onTaskChange(taskId, 'description', v)} />
          </FieldRow>
          <FieldRow label="Interval (s)">
            <NumberInput value={task.intervalSeconds} onChange={(v) => onTaskChange(taskId, 'intervalSeconds', v)} min={60} />
            <p className="text-[10px] text-zinc-600 mt-1">= {intervalLabel(task.intervalSeconds)}</p>
          </FieldRow>
          <TagList tags={task.required_capabilities ?? []} label="Requires" />
          <TagList tags={task.signal_triggers ?? []} label="Signal Triggers" />
          <TagList tags={task.emits_signals ?? []} label="Emits Signals" />
        </div>
      )}

      {activeTab === 'intelligence' && (
        <div className="space-y-3">
          <FieldRow label="Type">
            <SelectInput
              value={task.dispatch.type}
              onChange={(v) => onIntelligenceTypeChange(taskId, v)}
              options={DISPATCH_OPTIONS}
            />
          </FieldRow>
          <IntelligenceFields intelligence={task.dispatch} onChange={(f, v) => onIntelligenceChange(taskId, f, v)} requiredCapabilities={task.required_capabilities} />
          {(() => {
            const pf = getIntelligencePromptFile(task.dispatch)
            if (!pf) return null
            return (
              <div className="flex justify-end pt-1">
                <a
                  href={`/prompt/edit/${agentName}/${pf}`}
                  className="text-[10px] text-primary/70 hover:text-primary transition-colors"
                >
                  Open in Prompt Editor →
                </a>
              </div>
            )
          })()}
        </div>
      )}

      {activeTab === 'fallback' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-500">
              {fb
                ? 'Tried automatically if primary intelligence exits non-zero.'
                : 'No fallback configured — failed runs stay failed.'}
            </p>
            {fb ? (
              <button
                onClick={() => onFallbackToggle(taskId, false)}
                className="text-[10px] text-danger/70 hover:text-danger transition-colors shrink-0 ml-3"
              >
                Remove
              </button>
            ) : (
              <button
                onClick={() => onFallbackToggle(taskId, true)}
                className="text-[10px] text-primary/70 hover:text-primary transition-colors shrink-0 ml-3"
              >
                + Add Fallback
              </button>
            )}
          </div>
          {fb && (
            <>
              <FieldRow label="Type">
                <SelectInput
                  value={fb.type}
                  onChange={(v) => onFallbackTypeChange(taskId, v)}
                  options={DISPATCH_OPTIONS}
                />
              </FieldRow>
              <IntelligenceFields intelligence={fb} onChange={(f, v) => onFallbackChange(taskId, f, v)} />
              {(() => {
                const pf = getIntelligencePromptFile(fb)
                if (!pf) return null
                return (
                  <div className="flex justify-end pt-1">
                    <a
                      href={`/prompt/edit/${agentName}/${pf}`}
                      className="text-[10px] text-primary/70 hover:text-primary transition-colors"
                    >
                      Open in Prompt Editor →
                    </a>
                  </div>
                )
              })()}
            </>
          )}
        </div>
      )}
    </div>
  )
}
