# Spec — Agent Chat Dispatch

**Version:** 1.0
**Date:** 2026-06-14

---

## Purpose

Allows the GM dashboard chat UI to send messages directly to vault agents using each agent's configured LLM and system prompt — without requiring a separate API key or hardcoded provider.

---

## Architecture

```
Dashboard (browser)
  └─ POST /api/gm/chat
       └─ writes to .system/state/chat-queue.json  (status: pending)
       └─ spawns: python runner.py --chat-id <uuid>
            └─ reads agent.json → dispatch.type + dispatch config
            └─ loads prompts/system.md
            └─ calls configured LLM (LM Studio, Claude API, etc.)
            └─ writes response to chat-queue.json  (status: done | error)
       └─ reads response from queue → returns to browser
```

---

## Chat Queue

**Path:** `.system/state/chat-queue.json`

**Format:** JSON array of items:

```json
[
  {
    "id":        "uuid-v4",
    "agentName": "wiki",
    "message":   "User message (may include context appended)",
    "status":    "pending | processing | done | error",
    "response":  "LLM response text or null",
    "error":     "Error description or null",
    "createdAt": "ISO-8601",
    "updatedAt": "ISO-8601"
  }
]
```

Items accumulate in the queue (never auto-deleted). Clean up manually or via cleanup agent.

---

## Runner — `--chat-id` Mode

```
python runner.py --chat-id <uuid>
```

- Does **not** acquire the global run lock (chat is independent of scheduled tasks)
- Exits immediately after dispatching one item
- Exit code 0 = success, 1 = error (error written to queue item)

### Agent Name → Task ID Mapping

| `agentName` (dashboard) | `task_id` (agent.json) |
|-------------------------|------------------------|
| `lore`                  | `lore-agent`           |
| `wiki`                  | `wiki-agent`           |
| `classification`        | `classification-agent` |
| `vision`                | `vision-agent`         |
| `ingestion`             | `ingestion-agent`      |
| `repair`                | `repair-agent`         |
| `review`                | `review-agent`         |

### System Prompt Resolution

Loaded from (first match wins):

1. `.agents/<agentName>/prompts/system.md`
2. `.agents/<agentName>/prompts/system.txt`
3. Built-in DM assistant fallback

### LLM Dispatch

| `dispatch.type` | Behaviour |
|-----------------|-----------|
| `lm-studio`     | HTTP POST to `base_url/chat/completions` (OpenAI-compat) |
| `openai-api`    | Same as lm-studio |
| `claude-api`    | Anthropic SDK — requires `ANTHROPIC_API_KEY` env var |

Uses `model`, `max_tokens`, `temperature`, `timeout_seconds` from agent's dispatch config.

---

## Dashboard API

**Endpoint:** `POST /api/gm/chat`

**Request:**
```json
{ "message": "string", "agent": "wiki | lore | classification", "context": "optional string", "save": false }
```

**Response (success):**
```json
{ "role": "assistant", "content": "...", "timestamp": "ISO-8601", "agent": "wiki" }
```

**Response (error):**
```json
{ "error": "description" }
```

Timeout: 120 seconds (matches runner default).

---

## Supported Agents (Chat UI)

| Agent | Task ID | LLM |
|-------|---------|-----|
| Lore | `lore-agent` | per `agent.json` dispatch |
| Wiki | `wiki-agent` | per `agent.json` dispatch |
| Classification | `classification-agent` | per `agent.json` dispatch |

To add a new agent to the chat UI, add it to `AGENTS` in `.system/dashboard/src/app/gm/chat/page.tsx` and add the `agentName → task_id` entry to `_AGENT_NAME_TO_TASK` in `runner.py`.

---

## Implementation Files

| File | Role |
|------|------|
| `.agents/runtime/tools/runner.py` | `_dispatch_chat()`, `--chat-id` CLI arg |
| `.system/dashboard/src/app/api/gm/chat/route.ts` | Queue write + runner subprocess |
| `.system/state/chat-queue.json` | Runtime queue (auto-created) |
