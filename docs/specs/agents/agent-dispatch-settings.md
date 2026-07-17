# Agent Dispatch Settings

Snapshot of every agent's dispatch configuration, why it's set that way, and
what the next batch of (not-yet-built) agents should do differently.

## Active agents - dispatch: `lm-studio`

All 9 tool-using active agents run their agentic tool-call loop against a
local LM Studio model instead of the Claude API.

| Agent | Task ID | Model | Tools module | Interval |
|---|---|---|---|---|
| ingestion | ingestion-agent | `qwen/qwen3.5-9b` | `ingestion.tools.ingestion_agent` | 3600s |
| vision | vision-agent | `google/gemma-4-26b-a4b` | `vision.tools.classify_images` | 3600s |
| lore | lore-agent | `google/gemma-4-26b-a4b` | `lore.tools.generate_npcs` | 3600s |
| token | token-agent | `qwen/qwen3.5-9b` | `token.tools.generate_tokens` | 3600s |
| classification | classification-agent | `qwen/qwen3.5-9b` | `classification.tools.enrich_tags` | 3600s |
| wiki | wiki-agent | `google/gemma-4-26b-a4b` | `wiki.tools.compile_wiki` | 3600s |
| review | review-agent | `qwen/qwen3.5-9b` | `review.tools.daily_report` | 900s |
| review | review-agent-short-files | `qwen/qwen3.5-9b` | `review.tools.flag_short_files` | 3600s |
| wikilink | wikilink-agent | `qwen/qwen3.5-9b` | `wikilink.tools.wikilink_library` | 3600s |

All share: `base_url: http://localhost:1234/v1`, `timeout_seconds: 1800`,
`system_file: prompts/system.md` (or `prompts/system-short-files.md` for the
short-files task).

### Not dispatched via LLM

| Agent | Why |
|---|---|
| runtime | Python scheduler itself - not an AI agent. |
| repair | `llm: none` in registry.yaml - no `agent.json`, runs `repair_agent.py` directly (Bash tool / cron), no LLM call at all. |

## Reasoning

**Why LM Studio instead of Claude API (for the 9 active agents).** Every
agent previously dispatched via `claude-api`, which routes through the same
Anthropic account/OAuth token as this Claude Code session. That meant the
agents and this conversation competed for one shared rate-limit bucket -
confirmed via direct API probing (`claude-sonnet-4-6` returned 429 with no
`Retry-After` header even after a 3x backoff-retry). LM Studio runs fully
locally and unblocks the pipeline regardless of Anthropic-side quota. This
was validated end-to-end, not assumed: each agent was force-dispatched live
after the switch and confirmed to actually complete its task (draft written,
tags enriched, token generated, etc.), not just exit 0.

**Why the tool-call loop had to be built, not just config-swapped.** The
existing `lm-studio` dispatch type (`shared/runners/openai_compat.py`) was a
single-shot prompt/completion call with no concept of `tools_module` or
`call_tool()` - it could not run the same agentic loop the `claude-api`
runner supports. Added a second pattern to that runner (mirrors
`shared/runners/claude.py`'s `_run_tool_use`): converts each agent's
Anthropic-style `TOOLS` (name/description/input_schema) into OpenAI
function-calling schema, loops on `tool_calls` until `finish_reason == stop`,
retries 5xx/429 with `Retry-After`-aware backoff. Verified LM Studio's
function-calling support directly against the target models before wiring
any agent to it (`google/gemma-4-26b-a4b` and `qwen/qwen3.5-9b` both returned
correct `tool_calls` on a test call).

**Why two different models.** `google/gemma-4-26b-a4b` (bigger, better
reasoning) is used for the two generation-heavy agents - vision
(classification + draft writing) and lore/wiki (long-form NPC/wiki
content) - mirroring their previous `claude-sonnet-4-6` tier. The remaining
agents (ingestion, token, classification, review, wikilink) were previously
on `claude-haiku` - lightweight, mostly mechanical tool orchestration - so
they got the smaller/faster `qwen/qwen3.5-9b`, also tool-call-verified.
`classification-agent`'s first live run showed occasional "Empty LLM
response" warnings on this smaller model (caught and skipped by the agent's
own error handling, not fatal) - worth watching if it recurs; may need a
bigger model or a `max_tokens` bump for that one task specifically.

**The `prompt_file` → `system_file` bug, fixed everywhere.** Every one of
these 8 `agent.json` files had `"prompt_file": "prompts/system.md"` under a
`tools_module`-based (agentic) dispatch config. Per both runners' docstrings,
`prompt_file` is only read in the *non-agentic* single-prompt pattern -
`system_file` is what the tool-use loop actually loads as the system prompt.
So every agent's `prompts/system.md` (workflow instructions, tool-call order,
naming rules) was silently never applied - the model only ever saw the bare
"execute your scheduled task now" kickoff message. Fixed by renaming the key
to `system_file` in all 8 configs (vision already got this fix earlier).
This was a real, silent, long-standing bug independent of the LM
Studio/Claude-API question - it would have been just as broken running on
Claude.

## Guidance for planned (not-yet-built) agents

Registry status `planned`: `relationship`, `deduplication`, `canon`,
`curator`, `search`, `adventure-builder`, `session-builder`,
`encounter-builder`. None have an `agent.json` or tools module yet.

Per explicit direction: when these are built, **do not** wire them to a
direct LLM HTTP API (neither `claude-api` nor `lm-studio`) the way the
current 9 are. Use the `claude-code` dispatch type instead - it shells out to
the `claude` CLI (`claude -p <prompt> ...`) rather than calling
`client.messages.create()` directly. This is explicitly a stopgap ("make it
work" now) ahead of a proper agent harness - `claude-code` dispatch currently
runs with `--dangerously-skip-permissions` by default and has no
`tools_module`/`call_tool` constraint (full file+bash access instead of a
narrow registered tool set), so treat it as provisional, not the final
security model for these agents.
