# Spec — Agent Dispatch

---

## Overview

the runtime dispatches **agents**, not scripts. Each agent folder contains an `agent.json`
that declares how the runtime must invoke it. Dispatch type and provider config are isolated
per agent — the runtime never hardcodes invocation details.

---

## Agent Resolution

```
task.id → strip "-agent[-*]" suffix → .agents/{name}/ → agent.json
```

| task_id | agent folder |
|---|---|
| `repair-agent` | `.agents/repair/` |
| `review-agent` | `.agents/review/` |
| `review-agent-short-files` | `.agents/review/` |
| `ingestion-agent` | `.agents/ingestion/` |
| `vision-agent` | `.agents/vision/` |

If `.agents/{name}/agent.json` does not exist the runtime logs an error and skips the task.
`lastRun` is **not** updated on a skip.

---

## `agent.json` Schema

Location: `.agents/{name}/agent.json`

One agent folder may serve multiple task IDs (e.g. `review-agent` and `review-agent-short-files`
both map to `.agents/review/`). The `tasks` dict is keyed by task ID.

```json
{
  "tasks": {
    "<task-id>": {
      "dispatch": {
        "type": "cli | openai-api | claude-api | gemini-api | openrouter-api",
        ...provider block...
      }
    }
  }
}
```

the runtime looks up `task_id` in `tasks`. If the key is absent the task is skipped.

---

## Dispatch Types

### `cli`

Generic subprocess. Covers Python scripts, `claude` (Claude Code CLI), `codex`, `opencode`, or
any shell-accessible binary.

```json
{
  "dispatch": {
    "type": "cli",
    "cli": {
      "command": "python",
      "args": [".agents/repair/tools/repair_agent.py"],
      "cwd": "project_root",
      "timeout_seconds": 300,
      "env": {}
    }
  }
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `command` | string | yes | — | Executable name or absolute path |
| `args` | string[] | yes | `[]` | Argument list; relative paths are relative to `cwd` |
| `cwd` | `"project_root"` \| `"agent_dir"` | no | `"project_root"` | Working directory anchor |
| `timeout_seconds` | int | no | 300 | Kill process after N seconds |
| `env` | object | no | `{}` | Extra env vars merged with the process environment |

Exit code 0 = success. Non-zero = failure. stdout/stderr stream to the shared log.

**CLI agent examples:**

```json
{ "command": "python",   "args": [".agents/lore/tools/generate_npcs.py"] }
{ "command": "claude",   "args": ["--print", "--prompt-file", ".agents/wiki/prompts/main.md"] }
{ "command": "codex",    "args": ["run", ".agents/classification/prompts/main.md"] }
{ "command": "opencode", "args": ["--task", ".agents/vision/prompts/classify.md"] }
```

---

### `openai-api`

OpenAI REST API **or** any OpenAI-compatible endpoint (LM Studio, Ollama, LocalRouter).

```json
{
  "dispatch": {
    "type": "openai-api",
    "openai_api": {
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "prompt_file": ".agents/wiki/prompts/main.md",
      "system_file": ".agents/wiki/prompts/system.md",
      "max_tokens": 4096,
      "temperature": 0,
      "timeout_seconds": 120
    }
  }
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `base_url` | string | yes | — | API base URL. Use `http://localhost:1234/v1` for LM Studio |
| `model` | string | yes | — | Model identifier |
| `prompt_file` | string | no | — | Path to user prompt `.md` file (relative to project root) |
| `system_file` | string | no | — | Path to system prompt `.md` file |
| `max_tokens` | int | no | 1024 | Max completion tokens |
| `temperature` | float | no | 0 | Sampling temperature |
| `timeout_seconds` | int | no | 120 | HTTP request timeout |

Auth: `OPENAI_API_KEY` env var. For local endpoints set to any non-empty string (e.g. `"lm-studio"`).

---

### `claude-api`

Anthropic Claude API. Supports two patterns:

**Tool-use pattern** (primary — all active agents): Claude operates as an AI agent that calls tools defined in `tools_module`. The runtime runs a loop until the agent signals completion or `max_tool_rounds` is reached.

**Prompt pattern** (simple): Claude receives a prompt and returns a single text response. Used for one-shot generation tasks.

#### Tool-use pattern (active agents)

```json
{
  "dispatch": {
    "type": "claude-api",
    "claude_api": {
      "model": "claude-haiku-4-5-20251001",
      "system_file": "prompts/system.md",
      "tools_module": "ingestion.tools.ingestion_agent",
      "history_file": "ingestion-agent-history.json",
      "max_tokens": 2048,
      "timeout_seconds": 600,
      "max_tool_rounds": 15
    }
  }
}
```

#### Prompt pattern (simple generation)

```json
{
  "dispatch": {
    "type": "claude-api",
    "claude_api": {
      "model": "claude-sonnet-4-6",
      "system_file": "prompts/system.md",
      "prompt_file": "prompts/main.md",
      "max_tokens": 4096,
      "timeout_seconds": 120
    }
  }
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model` | string | yes | — | Model ID (e.g. `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`) |
| `system_file` | string | no | — | System prompt `.md` path, relative to agent dir (e.g. `prompts/system.md`) |
| `tools_module` | string | no | — | Python module path providing agent tools (e.g. `ingestion.tools.ingestion_agent`). Enables tool-use loop. |
| `history_file` | string | no | — | JSON file for conversation history, relative to agent state dir. Only used with `tools_module`. |
| `max_tool_rounds` | int | no | 10 | Max agent loop iterations before forced stop. Only used with `tools_module`. |
| `prompt_file` | string | no | — | User prompt `.md` path, relative to agent dir. Used in prompt pattern only (no `tools_module`). |
| `max_tokens` | int | no | 4096 | Max completion tokens |
| `temperature` | float | no | 0 | Sampling temperature |
| `timeout_seconds` | int | no | 120 | HTTP request timeout |

Auth: `ANTHROPIC_API_KEY` env var.

---

### `gemini-api`

Google Gemini API.

```json
{
  "dispatch": {
    "type": "gemini-api",
    "gemini_api": {
      "model": "gemini-2.5-flash",
      "prompt_file": ".agents/classification/prompts/main.md",
      "system_file": ".agents/classification/prompts/system.md",
      "max_tokens": 2048,
      "temperature": 0,
      "timeout_seconds": 120
    }
  }
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model` | string | yes | — | Model ID (e.g. `gemini-2.5-flash`, `gemini-2.5-pro`) |
| `prompt_file` | string | no | — | Path to user prompt `.md` |
| `system_file` | string | no | — | Path to system prompt `.md` |
| `max_tokens` | int | no | 2048 | Max output tokens |
| `temperature` | float | no | 0 | Sampling temperature |
| `timeout_seconds` | int | no | 120 | HTTP request timeout |

Auth: `GEMINI_API_KEY` env var.

---

### `openrouter-api`

OpenRouter unified gateway — any model available via OpenRouter.

```json
{
  "dispatch": {
    "type": "openrouter-api",
    "openrouter_api": {
      "model": "anthropic/claude-sonnet-4-6",
      "prompt_file": ".agents/adventure-builder/prompts/main.md",
      "system_file": ".agents/adventure-builder/prompts/system.md",
      "max_tokens": 8192,
      "temperature": 0,
      "timeout_seconds": 180
    }
  }
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model` | string | yes | — | OpenRouter model slug (e.g. `anthropic/claude-sonnet-4-6`, `google/gemini-2.5-flash`) |
| `prompt_file` | string | no | — | Path to user prompt `.md` |
| `system_file` | string | no | — | Path to system prompt `.md` |
| `max_tokens` | int | no | 4096 | Max completion tokens |
| `temperature` | float | no | 0 | Sampling temperature |
| `timeout_seconds` | int | no | 180 | HTTP request timeout |

Auth: `OPENROUTER_API_KEY` env var.

---

## Shared Runners

Location: `.agents/shared/runners/`

```
shared/
  runners/
    __init__.py        # IRunner protocol + RunResult + get_runner() factory
    cli.py             # CliRunner
    openai_compat.py   # OpenAICompatRunner  (openai-api + local endpoints)
    claude.py          # ClaudeRunner
    gemini.py          # GeminiRunner
    openrouter.py      # OpenRouterRunner
```

### `IRunner` protocol

```python
class RunResult:
    exit_code:   int        # 0 = success
    output:      str        # stdout or API response text
    error:       str | None # stderr or error message
    duration_ms: int

class IRunner(Protocol):
    def run(self, dispatch_config: dict, context: dict) -> RunResult: ...
```

### `get_runner()` factory

```python
def get_runner(dispatch_type: str) -> IRunner: ...
```

| `dispatch.type` | Runner class |
|---|---|
| `cli` | `CliRunner` |
| `openai-api` | `OpenAICompatRunner` |
| `claude-api` | `ClaudeRunner` |
| `gemini-api` | `GeminiRunner` |
| `openrouter-api` | `OpenRouterRunner` |

---

## Authentication

API keys are read from environment variables. Never stored in `agent.json`.

| Provider | Env var |
|---|---|
| OpenAI / LM Studio / Ollama / LocalRouter | `OPENAI_API_KEY` |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |

Local endpoints require `OPENAI_API_KEY` set to any non-empty value (e.g. `"lm-studio"`).

---

## Prompt Files

`prompt_file` and `system_file` paths in API dispatch configs are relative to the **agent directory** (e.g. `prompts/system.md` resolves to `.agents/{name}/prompts/system.md`).

- Files are plain Markdown (`.md`). Read fresh at dispatch time — not cached.
- `prompt_file` absent → runner sends empty user message.
- Prompt files may use `{{variable}}` placeholders resolved from the `context` dict.

Standard locations:
```
prompts/system.md   # system prompt (relative to agent dir)
prompts/main.md     # user prompt (relative to agent dir)
```

---

## Error Handling

| Condition | Behaviour |
|---|---|
| `agent.json` missing | Log error. Skip task. `lastRun` not updated. |
| Unknown `dispatch.type` | Log error. Skip task. `lastRun` not updated. |
| CLI non-zero exit | Log warning. Update `lastRun`. Skip git commit. |
| API 401 / 403 | Log error. Update `lastRun`. Skip git commit. |
| API timeout | Log error. Update `lastRun`. Skip git commit. |
| API 5xx (transient) | Retry up to 3× with 3s backoff. Then log error. Update `lastRun`. Skip git commit. |
