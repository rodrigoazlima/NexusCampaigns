# Agent Architecture

This directory is the agent layer of the Nexus Campaigns. Each subdirectory is an autonomous agent with clear ownership of tools, state, and responsibilities.

---

## Design Principles

| Principle | Rule |
|-----------|------|
| Scripts are tools | Scripts never run standalone — they are owned and invoked by an agent |
| State isolation | Each agent owns its state files under `{agent}/state/` |
| Shared minimum | Code moves to `.system/` only when used by 3+ agents |
| No self-approval | Agents may never set `reviewed: true` or promote to `02-Library/` |
| Human gate | Canon requires explicit human action — no automation bypasses it |
| CLI-agnostic | Agents declare `allowed_clis` — orchestrator decides which to use |
| Model-swappable | Agents declare `preferred_models` — swap without touching tool code |

---

## Pipeline

```
00-Inbox
    │
    ▼
┌─────────────┐
│  ingestion  │  Normalize filenames, convert DOCX, register files in inbox-queue.json
└──────┬──────┘
       │ .system/state/inbox-queue.json
       ▼
┌──────┴─────────────────────────────────────────┐
│                                                │
▼                    ▼                           ▼
vision              wiki                    (classification runs after both)
│                    │
▼                    ▼
lore            01-Processing/
│
▼
token
│
▼
01-Processing/
       │
       ▼
┌─────────────────┐
│  classification │  Enrich tags + type inference + duplicate detection
└────────┬────────┘
         │
         ▼
┌────────────────┐
│    review      │  Vault health, quality scores, pending list — every 15 min
└────────────────┘
         │
         ▼
   Human Review
         │
         ▼
    02-Library  ← canon
```

---

## Active Agents

| Agent | Interval | LLM | Purpose |
|-------|----------|-----|---------|
| [runtime](orchestrator/AGENT.md) | 1 min | none | Dispatches all agents, git commit/push |
| [ingestion](ingestion/AGENT.md) | 1 h | none | Normalize inbox, DOCX→MD, queue registration |
| [vision](vision/AGENT.md) | 1 h | Qwen3-VL @ :1234 | Image classification, slug rename, draft entity |
| [lore](lore/AGENT.md) | 1 h | Qwen3-VL @ :1234 | PF2e NPC generation from images × scenarios |
| [token](token/AGENT.md) | 1 h | none | Circular portrait token generation (CV only) |
| [wiki](wiki/AGENT.md) | 1 h | LocalRouter @ :8080 | Compile inbox notes → structured entity drafts |
| [classification](classification/AGENT.md) | 1 h | LocalRouter @ :8080 | Tag enrichment, type inference, dedup check |
| [review](review/AGENT.md) | 15 min | none | Vault health report, quality scores |

---

## Planned Agents

| Agent | Depends On | Purpose |
|-------|-----------|---------|
| [canon](canon/AGENT.md) | — | Consistency validation across 02-Library/ |
| [relationship](relationship/AGENT.md) | canon | Wikilink graphs, faction/NPC networks → 04-Relationships/ |
| [deduplication](deduplication/AGENT.md) | classification | Semantic dedup, merge candidate reports |
| [curator](curator/AGENT.md) | review, classification | Promotion readiness scoring (never auto-promotes) |
| [search](search/AGENT.md) | canon | Vector index, semantic retrieval |
| [adventure-builder](adventure-builder/AGENT.md) | lore, canon, relationship | Campaign modules → 03-Campaigns/ |
| [session-builder](session-builder/AGENT.md) | adventure-builder | Per-session prep docs → 03-Campaigns/ |
| [encounter-builder](encounter-builder/AGENT.md) | lore, vision, canon | PF2e encounter stat blocks → 03-Campaigns/ |

---

## Agent Directory Structure

Every agent follows this layout:

```
{agent}/
  AGENT.md          ← definition: purpose, inputs, outputs, restrictions
  skills/           ← agent capabilities (future)
  prompts/          ← LLM prompt templates (extracted from tools)
  tools/            ← scripts this agent owns
  generated-tools/  ← tools the agent created itself at runtime
  state/            ← all state files owned by this agent
    logs/           ← per-agent daily log rotation
```

Agents may **create** tools inside `generated-tools/`. They may **never** create tools outside their own directory.

---

## AGENT.md Schema

Every `AGENT.md` must contain these YAML fields:

```yaml
name:             # kebab-case identifier
purpose:          # one-paragraph description
inputs:           # list of paths/endpoints read
outputs:          # list of paths/endpoints written
dependencies:     # other agents that must run first
allowed_clis:     # [claude-code, opencode, codex, gemini-cli, ...]
preferred_models:
  primary:        # model id or endpoint alias
  fallbacks:      # ordered list
owned_tools:      # tools/ paths this agent runs
responsibilities: # bullet list of what it does
restrictions:     # hard constraints (what it must NOT do)
state_files:      # state/ paths this agent owns
```

---

## Shared Resources

```
.system/
  state/
    inbox-queue.json    ← written by ingestion; updated by vision, lore, wiki
  utils/
    Write-Log.ps1       ← shared logging function (used by all PS scripts)
    Invoke-LLMCall.ps1  ← retry-aware LLM REST wrapper
    Read-Frontmatter.ps1
    Write-Frontmatter.ps1
    Read-InboxQueue.ps1
    Write-InboxQueue.ps1
```

Code belongs in `.system/utils/` only when **3 or more agents** use it. Otherwise keep it local.

---

## LLM Endpoints

| Alias | URL | Model | Used By |
|-------|-----|-------|---------|
| `vision_llm` | `localhost:1234` | `qwen3-vl-4b-instruct` | vision, lore |
| `local_router` | `localhost:8080` | `auto` | wiki, classification |

To swap a model: update `registry.yaml` `llm_endpoints` section. No script changes needed after Phase 3 (once prompts are extracted).

---

## Adding a New Agent

1. Create `.agents/{name}/` with standard subdirs (`skills/`, `prompts/`, `tools/`, `generated-tools/`, `state/`, `state/logs/`)
2. Write `AGENT.md` following the schema above
3. Add entry to `registry.yaml` under `agents:`
4. If agent runs on a schedule: add entry to `.agents/runtime/state/agent.json`
5. Add entry to `.agents/runtime/state/tasks-state.json` with `lastRun: "1970-01-01T00:00:00.0000000Z"`
6. Place tool scripts in `tools/`
7. Do **not** modify any existing agent's files

New agents can be added without touching existing agents.

---

## Registry

`registry.yaml` is the single source of truth for:
- All agent names and statuses
- Execution order
- LLM endpoint aliases
- Shared state file ownership
- Tool and prompt paths per agent

---

## State File Ownership

| File | Owner | Location |
|------|-------|----------|
| `inbox-queue.json` | ingestion (writes) / all (update) | `.system/state/` |
| `processed-images.json` | vision | `.agents/vision/state/` |
| `token-links.json` | vision | `.agents/vision/state/` |
| `processed-npcs.json` | lore | `.agents/lore/state/` |
| `scenarios.json` | lore | `.agents/lore/state/` |
| `generated-tokens.json` | token | `.agents/token/state/` |
| `10-generate-tokens.json` | token | `.agents/token/state/` |
| `bad-docs.txt` | classification | `.agents/classification/state/` |
| `processed.txt` | wiki | `.agents/wiki/state/` |
| `bad-wiki-docs.txt` | wiki | `.agents/wiki/state/` |
| `processed-docx.txt` | ingestion | `.agents/ingestion/state/` |
| `agent.json` | orchestrator | `.agents/runtime/state/` |
| `tasks-state.json` | orchestrator | `.agents/runtime/state/` |
| `reports/` | review | `.agents/review/state/` |
| `logs/automation.log` | orchestrator | `.agents/runtime/state/logs/` |

---

## Execution Flow

```
Windows Task Scheduler  (every 1 min)
  └─ runner.ps1  [runtime]
       ├─ load agent.json discovery + tasks-state.json
       ├─ for each due task:
       │    ├─ invoke tool script
       │    ├─ write logs
       │    └─ git add -A → commit → push
       └─ update tasks-state.json
```

---

## Migration Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Directory scaffold + AGENT.md files + registry | ✅ Done |
| Phase 1 | State files copied to agent state dirs, scripts path-updated | ⬜ Pending |
| Phase 2 | Scripts moved to agent tools dirs, agent.json updated | ⬜ Pending |
| Phase 3 | LLM prompts extracted to prompts/ files | ⬜ Pending |
| Phase 4 | Shared PS utilities extracted to .system/utils/ | ⬜ Pending |
| Phase 5 | Future agent skeletons completed | ⬜ Pending |
