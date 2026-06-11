# Spec — LLM Integration

---

## Overview

LLM calls are declared in each agent's `agent.json` dispatch config, not in the runtime
or shared code. Provider selection, endpoint, model, and auth are agent-local decisions.

See [agent-dispatch.spec.md](agent-dispatch.spec.md) for the full provider config schema
(`openai-api`, `claude-api`, `gemini-api`, `openrouter-api`).

---

## Provider Reference

| Provider | `dispatch.type` | Base URL | Auth env var |
|---|---|---|---|
| OpenAI | `openai-api` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| LM Studio (local) | `openai-api` | `http://localhost:1234/v1` | `OPENAI_API_KEY=lm-studio` |
| LocalRouter (local) | `openai-api` | `http://localhost:8080/v1` | `OPENAI_API_KEY=lm-studio` |
| Anthropic Claude | `claude-api` | _(SDK-managed)_ | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini-api` | _(SDK-managed)_ | `GEMINI_API_KEY` |
| OpenRouter | `openrouter-api` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |

---

## Current Agent Assignments

All active agents use `dispatch.type: claude-api` — Claude operates as the AI agent and calls
Python tools via the tool-use loop. Some agents' tools make additional LLM calls internally
(to local endpoints) for vision classification and text synthesis.

| Agent | Dispatch type | Claude model | Internal LLM (tool calls) | Purpose |
|---|---|---|---|---|
| Vision | `claude-api` | `claude-sonnet-4-6` | `qwen3-vl-4b-instruct` @ `localhost:1234` | Image classification |
| Lore | `claude-api` | `claude-sonnet-4-6` | `qwen3-vl-4b-instruct` @ `localhost:1234` | NPC sheet generation |
| Classification | `claude-api` | `claude-haiku-4-5-20251001` | `auto` @ `localhost:8080` | Tag enrichment |
| Wiki | `claude-api` | `claude-sonnet-4-6` | `auto` @ `localhost:8080` | Entity page synthesis |
| Ingestion | `claude-api` | `claude-haiku-4-5-20251001` | none | Queue registration, DOCX conversion |
| Review | `claude-api` | `claude-haiku-4-5-20251001` | none | Vault health report |
| Repair | `claude-api` | `claude-haiku-4-5-20251001` | none | Stale lock + dir repair |
| Token | `claude-api` | `claude-haiku-4-5-20251001` | none | Token frame compositing |
| Wikilink | `claude-api` | `claude-haiku-4-5-20251001` | none | Cross-link insertion |
| Cleanup | `claude-api` | `claude-haiku-4-5-20251001` | none | Log/report rotation |

---

## Call Parameters

These defaults apply to all LLM-backed dispatch types unless overridden in `agent.json`:

| Parameter | Default | Notes |
|---|---|---|
| `temperature` | `0` | Deterministic output |
| `max_tokens` | `1024` | Override per agent |
| Retries | 3 | 3s backoff between attempts |
| Connection error | skip batch | No permanent failure recorded |

### Per-agent overrides (current)

| Agent | `max_tokens` | `temperature` |
|---|---|---|
| Vision | 350 | 0 |
| Lore | 700 | 0 |
| Classification | 80 (tag), 10 (type) | 0 |
| Wiki | 1500 | 0.3 |

---

## Vision Payload Encoding

Agents that send images (Vision, Lore):

- Resize image to max 1024px on longest side before encoding
- Encode as base64 JPEG at 85% quality
- Include in `content[].image_url.url` as `data:image/jpeg;base64,{b64}`
- Connection error (server offline) → skip batch silently; do not mark image as failed

---

## Open Design Items

| # | Item | Status |
|---|---|---|
| 1 | Vision + Lore use LM Studio locally; no cloud fallback defined | Open |
| 2 | Classification / Wiki use separate LocalRouter port (8080) — migrate to unified `agent.json` per-agent config | Open |
| 3 | Face matching distance threshold and match method not formally specified | Open |
