# Spec — Dashboard Agent Configuration Dialog

---

## Overview

`AgentConfigDialog` is the UI surface for inspecting and editing `agent.json` per-agent configuration. It maps directly to the `TaskConfig` / `IntelligenceConfig` schema and writes back via `PUT /api/config/{agentName}`. Closing after a successful save is required.

---

## Entry Point

Component: `system/dashboard/src/components/agents/AgentConfigDialog.tsx`  
Opened from: agent list or agent card click.  
Props: `agentName`, `agentDisplayName`, `open`, `onClose`.

---

## Layout

```
┌──────────────────────────────────────────────┐
│ Agent Config — {displayName}          [×]    │
├──────────────────────────────────────────────┤
│ [General] [Intelligence] [Fallback]          │  ← TaskForm tabs
│                                              │
│  (tab content)                               │
│                                              │
├──────────────────────────────────────────────┤
│  [Save]        (status badge)                │
└──────────────────────────────────────────────┘
```

Multiple tasks → outer tab row above TaskForm selects the active task.

---

## Tabs

### General

| Field | Type | Notes |
|-------|------|-------|
| Description | text | `task.description` |
| Interval (s) | number | `task.intervalSeconds`, min 60; humanised label shown below |
| Requires | tags (read-only) | `task.required_capabilities` — see Capability System |
| Signal Triggers | tags (read-only) | `task.signal_triggers` |
| Emits Signals | tags (read-only) | `task.emits_signals` |

### Intelligence

Provider type selector + provider-specific fields.  
Capability warnings rendered **above** provider fields when the selected provider does not fully cover `required_capabilities`.

Type options:

| Value | Label |
|-------|-------|
| `claude-api` | Claude API |
| `claude-code` | Claude Code CLI |
| `codex-cli` | Codex CLI |
| `lm-studio` | LM Studio |
| `openai-api` | OpenAI API |
| `gemini-api` | Gemini API |
| `openrouter-api` | OpenRouter API |
| `cli` | CLI |

### Fallback

Same provider fields as Intelligence tab.  
Toggle enables/disables fallback dispatch.  
Disabled state shows: `"No fallback configured — failed runs stay failed."`  
Enabled state shows: `"Tried automatically if primary intelligence exits non-zero."`

---

## Capability System

### `required_capabilities` (per task in `agent.json`)

Type: `Array<'vision' | 'text' | 'speech' | 'tool-call'>`

Declares what the task needs from its intelligence provider. Human-set; never written by agents.

### Provider capability map

| Provider | Definite | Uncertain (model-dependent) |
|----------|----------|-----------------------------|
| `claude-api` | vision, text, tool-call | — |
| `claude-code` | text, tool-call | — |
| `codex-cli` | text, tool-call | — |
| `openai-api` | text | vision, tool-call |
| `gemini-api` | text, tool-call | vision |
| `openrouter-api` | text | vision, tool-call |
| `lm-studio` | text | vision, tool-call |
| `cli` | — | — |

### Warning rendering

- **Red banner (`✕`)** — capability is required but provider definitively does not support it.
- **Yellow banner (`⚠`)** — capability is required; provider *may* support it depending on the specific model loaded.

Both banners have `role="alert"` and `aria-label` on the icon for accessibility.

---

## Provider Field Reference

### Claude API (`claude-api`)

| Field | Key | Type |
|-------|-----|------|
| Model | `model` | text |
| Max Tokens | `max_tokens` | number |
| Temperature | `temperature` | slider 0–1 |
| Timeout (s) | `timeout_seconds` | number |
| System File | `system_file` | text (nullable) |
| Prompt File | `prompt_file` | text (nullable) |

### Claude Code CLI (`claude-code`)

| Field | Key | Notes |
|-------|-----|-------|
| Prompt File | `prompt_file` | relative to agent dir |
| Inline Prompt | `prompt` | used when prompt_file empty |
| Extra Args | `extra_args` | one per line; include `--dangerously-skip-permissions` |
| CWD | `cwd` | `project_root` \| `agent_dir` |
| Timeout (s) | `timeout_seconds` | |
| Env Vars | `env` | JSON object |

### Codex CLI (`codex-cli`)

| Field | Key | Notes |
|-------|-----|-------|
| Prompt File | `prompt_file` | |
| Inline Prompt | `prompt` | |
| Model | `model` | e.g. `o4-mini` |
| Approval Mode | `approval_mode` | `suggest` \| `auto-edit` \| `full-auto` |
| Extra Args | `extra_args` | one per line |
| CWD | `cwd` | |
| Timeout (s) | `timeout_seconds` | |
| Env Vars | `env` | JSON object |

### LM Studio (`lm-studio`)

| Field | Key | Notes |
|-------|-----|-------|
| Base URL | `base_url` | default `http://localhost:1234/v1` |
| Model | `model` | fetched from `{base_url}/models` on mount; select when reachable, text input + refresh button when not |
| Max Tokens | `max_tokens` | |
| Temperature | `temperature` | |
| Timeout (s) | `timeout_seconds` | |
| System File | `system_file` | |
| Prompt File | `prompt_file` | |

Model fetch: `GET {base_url}/models` → `data[].id`. Falls back to text input on error with message `"LM Studio not reachable — enter model ID manually"`. Refresh button (`↻`) re-fetches on demand.

### OpenAI API (`openai-api`)

Base URL + Model + Max Tokens + Temperature + Timeout + System File + Prompt File.

### Gemini / OpenRouter (`gemini-api`, `openrouter-api`)

Model + Max Tokens + Temperature + Timeout + System File + Prompt File.

### CLI (`cli`)

Command + Args (one per line) + CWD + Timeout + Env Vars.

---

## Save Behaviour

1. `PUT /api/config/{agentName}` with full config JSON.
2. On success: show `✓` badge, **close dialog** (`onClose()`).
3. On error: show error message; dialog stays open.
4. Save button disabled while request in-flight.

---

## Types

```typescript
// system/dashboard/src/lib/types.ts

type AgentCapability = 'vision' | 'text' | 'speech' | 'tool-call'

interface TaskConfig {
  intervalSeconds: number
  description: string
  required_capabilities?: AgentCapability[]
  dispatch: IntelligenceConfig
  fallback_dispatch?: IntelligenceConfig
  signal_triggers?: string[]
  emits_signals?: string[]
}

interface IntelligenceConfig {
  type: 'cli' | 'claude-api' | 'openai-api' | 'gemini-api' | 'openrouter-api'
       | 'claude-code' | 'codex-cli' | 'lm-studio'
  cli?: CliConfig
  claude_api?: ClaudeApiConfig
  openai_api?: OpenAIApiConfig
  gemini_api?: GeminiApiConfig
  openrouter_api?: OpenRouterApiConfig
  claude_code?: ClaudeCodeConfig
  codex_cli?: CodexCliConfig
  lm_studio?: LmStudioConfig
}
```

---

## `agent.json` capability annotation

```json
{
  "tasks": {
    "vision-agent": {
      "required_capabilities": ["vision", "text", "tool-call"],
      "dispatch": { ... }
    }
  }
}
```

Agents requiring vision: `vision-agent`, `lore-agent`, `token-agent`.  
Agents requiring text + tool-call only: `ingestion-agent`, `classification-agent`, `wiki-agent`, `wikilink-agent`, `review-agent`.
