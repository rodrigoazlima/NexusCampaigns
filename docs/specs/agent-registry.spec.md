# Spec — Agent Registry

`registry.yaml` is the single source of truth for all agents, LLM endpoints, execution order, and shared state ownership. Location: `.agents/registry.yaml`.

---

## Schema

```yaml
version: 1
vault_root:  "<absolute path to knowledge-base/>"
agents_dir:  ".agents"
shared_dir:  ".shared"

llm_endpoints:
  <alias>:
    url:      "<base URL>"
    model:    "<model identifier>"
    type:     "vision | text"
    provider: "lm-studio | local-router | anthropic | openai | gemini | openrouter"

execution_order:
  - <agent-name>     # ordered list; runtime dispatches in this order

shared_state_files:
  <filename>:
    path:     "<relative path from project root>"
    owner:    "<agent-name>"
    updaters:
      - <agent-name>

agents:
  <agent-name>:
    status:           "active | planned | deprecated"
    task_id:          "<task-id>"          # matches tasks-state.json key; omit for runtime
    description:      "<one-line purpose>"
    interval_seconds: <int>
    llm:              "<llm_endpoints alias> | none"
    tools:
      - <relative path to tool script>
    prompts:
      - <relative path to prompt file>
    shared_state:
      reads:
        - <path>
      writes:
        - <path>
      updates:
        - <path>
    dependencies:      # planned agents only
      - <agent-name>
```

---

## Active Agents

| Name | task_id | Interval | LLM |
|------|---------|----------|-----|
| runtime | _(dispatcher)_ | 60s | none |
| repair | `repair-agent` | 900s | none |
| ingestion | `ingestion-agent` | 3600s | none |
| vision | `vision-agent` | 3600s | `vision_llm` |
| lore | `lore-agent` | 3600s | `vision_llm` |
| token | `token-agent` | 3600s | none |
| wiki | `wiki-agent` | 3600s | `local_router` |
| classification | `classification-agent` | 3600s | `local_router` |
| review | `review-agent` | 900s | none |
| wikilink | `wikilink-agent` | 3600s | none |
| cleanup | `cleanup-agent` | 86400s | none |

---

## Planned Agents

| Name | Depends On | Purpose |
|------|-----------|---------|
| canon | — | Consistency validation across `02-Library/` |
| relationship | canon | Wikilink graphs, faction/NPC networks → `04-Relationships/` |
| deduplication | classification | Semantic dedup, merge candidate reports |
| curator | review, classification | Promotion readiness scoring (never auto-promotes) |
| search | canon | Vector index, semantic retrieval |
| adventure-builder | lore, canon, relationship | Campaign modules → `03-Campaigns/` |
| session-builder | adventure-builder | Per-session prep docs → `03-Campaigns/` |
| encounter-builder | lore, vision, canon | PF2e encounter stat blocks → `03-Campaigns/` |

---

## LLM Endpoints

Defined under `llm_endpoints`. Referenced by agent `llm:` field.

| Alias | URL | Model | Used By |
|-------|-----|-------|---------|
| `vision_llm` | `localhost:1234/v1` | `qwen3-vl-4b-instruct` | vision, lore |
| `local_router` | `localhost:8080/v1` | `auto` | wiki, classification |

To swap a model or endpoint: edit `registry.yaml` `llm_endpoints` only. No tool code changes needed.

---

## Adding a New Agent

1. Create `.agents/{name}/` with subdirs: `prompts/`, `tools/`, `generated-tools/`, `state/`, `state/logs/`
2. Write `AGENT.md` following the schema in `.agents/README.md`
3. Add entry under `agents:` in `registry.yaml` with `status: active`
4. Add entry under `tasks:` in the agent's `agent.json` with dispatch config
5. Add entry to `.agents/runtime/state/tasks-state.json`: `{ "task-id": { "lastRun": "1970-01-01T00:00:00Z" } }`
6. Add `task-id` to `execution_order` in registry.yaml at the appropriate position
