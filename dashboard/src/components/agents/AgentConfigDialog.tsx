'use client'

import { useEffect, useState, useCallback } from 'react'
import { X, AlertTriangle, Loader2, CheckCircle } from 'lucide-react'
import type { AgentConfig, RuntimeConfig, DispatchConfig } from '@/lib/types'

interface AgentConfigDialogProps {
  agentName: string
  agentDisplayName: string
  open: boolean
  onClose: () => void
}

type ConfigData = AgentConfig | RuntimeConfig

const TYPE_KEY_MAP: Record<string, keyof DispatchConfig> = {
  'cli': 'cli',
  'claude-api': 'claude_api',
  'openai-api': 'openai_api',
  'gemini-api': 'gemini_api',
  'openrouter-api': 'openrouter_api',
  'claude-code': 'claude_code',
}

const DEFAULT_DISPATCH: Record<string, Record<string, unknown>> = {
  'cli': { command: '', args: [], cwd: 'project_root', timeout_seconds: 300, env: {} },
  'claude-api': { model: 'claude-haiku-4-5-20251001', max_tokens: 4096, temperature: 0.0, timeout_seconds: 120, max_tool_rounds: 20 },
  'openai-api': { base_url: '', model: '', max_tokens: 1024, temperature: 0.0, timeout_seconds: 120 },
  'gemini-api': { model: '', max_tokens: 2048, temperature: 0.0, timeout_seconds: 120 },
  'openrouter-api': { model: '', max_tokens: 4096, temperature: 0.0, timeout_seconds: 180 },
  'claude-code': { prompt_file: 'prompts/prompt.md', prompt: null, extra_args: [], dangerously_skip_permissions: true, cwd: 'project_root', timeout_seconds: 600, env: {} },
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
  const extraArgsText = Array.isArray(cfg.extra_args) ? (cfg.extra_args as string[]).join('\n') : ''
  const envText = cfg.env ? JSON.stringify(cfg.env, null, 2) : '{}'
  const skipPerms = cfg.dangerously_skip_permissions !== false

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
          rows={2}
          mono
        />
        <p className="text-[10px] text-zinc-600 mt-1">One arg per line; appended after --dangerously-skip-permissions</p>
      </FieldRow>
      <FieldRow label="Skip Permissions">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={skipPerms}
            onChange={(e) => onChange('dangerously_skip_permissions', e.target.checked)}
            className="accent-primary"
          />
          <span className="text-xs text-zinc-300">--dangerously-skip-permissions (enabled by default)</span>
        </label>
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
      setTimeout(() => setSaveStatus('idle'), 3000)
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

  const updateDispatchField = useCallback((taskId: string, field: string, value: unknown) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      const dispatch = next.tasks[taskId].dispatch
      const key = TYPE_KEY_MAP[dispatch.type]
      if (key && dispatch[key]) {
        (dispatch[key] as unknown as Record<string, unknown>)[field] = value
      }
      return next
    })
  }, [])

  const updateDispatchType = useCallback((taskId: string, newType: string) => {
    setConfig((prev) => {
      if (!prev || isRuntimeConfig(prev)) return prev
      const next = JSON.parse(JSON.stringify(prev)) as AgentConfig
      const task = next.tasks[taskId]
      const oldKey = TYPE_KEY_MAP[task.dispatch.type]
      const newKey = TYPE_KEY_MAP[newType]
      if (oldKey) delete task.dispatch[oldKey]
      task.dispatch.type = newType as DispatchConfig['type']
      if (newKey) {
        task.dispatch[newKey] = { ...(DEFAULT_DISPATCH[newType] ?? {}) } as never
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
                  config={config}
                  onTopLevelChange={updateTopLevel}
                  onTaskChange={updateTask}
                  onDispatchChange={updateDispatchField}
                  onDispatchTypeChange={updateDispatchType}
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
// Agent form
// ---------------------------------------------------------------------------

function AgentForm({
  config, onTopLevelChange, onTaskChange, onDispatchChange, onDispatchTypeChange,
}: {
  config: AgentConfig
  onTopLevelChange: (field: string, value: unknown) => void
  onTaskChange: (taskId: string, field: string, value: unknown) => void
  onDispatchChange: (taskId: string, field: string, value: unknown) => void
  onDispatchTypeChange: (taskId: string, newType: string) => void
}) {
  const taskEntries = Object.entries(config.tasks)

  return (
    <div className="space-y-6">
      {config.cleanupDays !== undefined && (
        <div>
          <div className="text-[10px] uppercase tracking-widest text-zinc-500 mb-3">Top-level</div>
          <div className="space-y-3">
            <FieldRow label="Cleanup Days">
              <NumberInput value={config.cleanupDays} onChange={(v) => onTopLevelChange('cleanupDays', v)} min={1} />
            </FieldRow>
          </div>
        </div>
      )}

      {taskEntries.map(([taskId, task], idx) => (
        <div key={taskId}>
          {idx > 0 && <div className="border-t border-surface-3" />}
          <div className="text-[10px] uppercase tracking-widest text-zinc-500 mb-3 font-mono">{taskId}</div>
          <TaskForm
            taskId={taskId}
            task={task}
            onTaskChange={onTaskChange}
            onDispatchChange={onDispatchChange}
            onDispatchTypeChange={onDispatchTypeChange}
          />
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Task form
// ---------------------------------------------------------------------------

function TaskForm({
  taskId, task, onTaskChange, onDispatchChange, onDispatchTypeChange,
}: {
  taskId: string
  task: import('@/lib/types').TaskConfig
  onTaskChange: (taskId: string, field: string, value: unknown) => void
  onDispatchChange: (taskId: string, field: string, value: unknown) => void
  onDispatchTypeChange: (taskId: string, newType: string) => void
}) {
  const dispatch = task.dispatch
  const dispatchKey = TYPE_KEY_MAP[dispatch.type]
  const dispatchCfg = (dispatchKey ? dispatch[dispatchKey] : null) as Record<string, unknown> | null

  return (
    <div className="space-y-3">
      <FieldRow label="Description">
        <TextInput value={task.description} onChange={(v) => onTaskChange(taskId, 'description', v)} />
      </FieldRow>
      <FieldRow label="Interval (s)">
        <NumberInput value={task.intervalSeconds} onChange={(v) => onTaskChange(taskId, 'intervalSeconds', v)} min={60} />
        <p className="text-[10px] text-zinc-600 mt-1">= {intervalLabel(task.intervalSeconds)}</p>
      </FieldRow>

      <TagList tags={task.signal_triggers ?? []} label="Signal Triggers" />
      <TagList tags={task.emits_signals ?? []} label="Emits Signals" />

      {/* Dispatch */}
      <div className="mt-4 pt-4 border-t border-surface-3/50">
        <div className="text-[10px] uppercase tracking-widest text-zinc-600 mb-3">Dispatch</div>
        <div className="space-y-3">
          <FieldRow label="Type">
            <SelectInput
              value={dispatch.type}
              onChange={(v) => onDispatchTypeChange(taskId, v)}
              options={[
                { value: 'claude-api', label: 'Claude API' },
                { value: 'claude-code', label: 'Claude Code CLI' },
                { value: 'openai-api', label: 'OpenAI API' },
                { value: 'gemini-api', label: 'Gemini API' },
                { value: 'openrouter-api', label: 'OpenRouter API' },
                { value: 'cli', label: 'CLI' },
              ]}
            />
          </FieldRow>

          {dispatchCfg && dispatch.type === 'claude-api' && (
            <ClaudeApiFields cfg={dispatchCfg} onChange={(f, v) => onDispatchChange(taskId, f, v)} />
          )}
          {dispatchCfg && dispatch.type === 'openai-api' && (
            <OpenAIApiFields cfg={dispatchCfg} onChange={(f, v) => onDispatchChange(taskId, f, v)} />
          )}
          {dispatchCfg && (dispatch.type === 'gemini-api' || dispatch.type === 'openrouter-api') && (
            <GeminiOrOpenRouterFields cfg={dispatchCfg} onChange={(f, v) => onDispatchChange(taskId, f, v)} />
          )}
          {dispatchCfg && dispatch.type === 'cli' && (
            <CliFields cfg={dispatchCfg} onChange={(f, v) => onDispatchChange(taskId, f, v)} />
          )}
          {dispatchCfg && dispatch.type === 'claude-code' && (
            <ClaudeCodeFields cfg={dispatchCfg} onChange={(f, v) => onDispatchChange(taskId, f, v)} />
          )}
        </div>
      </div>
    </div>
  )
}
