# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Install the nexus package (editable) + deps
python -m pip install -e ".[test]"

# Run the full test suite (pyproject.toml sets testpaths = tests)
pytest
pytest tests/test_11_ingestion_agent.py        # single file
pytest tests/test_11_ingestion_agent.py::test_x -k x  # single test
pytest -m e2e                                  # end-to-end tests (need network + Pillow)

# Run the scheduler once (dry loop) vs a single task, bypassing due/precondition checks
python -m nexus.runner --once
python -m nexus.runner --task ingestion-agent --force

# Run a static (no-LLM) task directly
python -m nexus.tasks.repair_agent

# Start the always-on daemon (what the Windows service wraps)
powershell -NonInteractive -File system\ops\daemon.ps1

# One-command install / status / uninstall / clean reinstall
pwsh -ExecutionPolicy Bypass -File system\ops\setup-service.ps1
pwsh -File system\ops\setup-service.ps1 -Status
pwsh -File system\ops\setup-service.ps1 -Uninstall
pwsh -File system\ops\setup-service.ps1 -CleanInstall

# Dashboard dev server
cd system\dashboard; npm run dev

# Live log tail
Get-Content 'agents\runtime\state\logs\automation.log' -Tail 50 -Wait
```

## Architecture

**Two repos, one working tree.** `.knowledge-base/` is an NTFS junction/symlink to a separate vault repo (content, gitignored from this repo's perspective). `system/src/nexus/` is the installable Python package (`pip install -e .`): `nexus.runner` (scheduler), `nexus.shared` (agent library), `nexus.tasks` (all static, no-LLM task scripts — cleanup, ingestion, repair, review, thumbnails, token, wikilink). `agents/<name>/` folders hold per-agent manifests (`agent.json`, `AGENT.md`, `state/`) plus, for the LLM-driven agents only (vision, lore, classification, wiki), their `tools/` code and prompts. `system/dashboard/` is the Next.js UI; `system/ops/` holds the daemon/service install scripts.

**Runtime dispatch loop** (`nexus/runner.py`):
1. `_discover_tasks()` globs `agents/*/agent.json`, orders tasks by `execution_order` in `agents/registry.yaml` (fallback: alphabetical).
2. Each cycle checks `is_due()` (elapsed ≥ `intervalSeconds` since `state/tasks-state.json`) OR a pending signal in `state/signals/` (`SignalConsumer`/`nexus/shared/signal_bus.py`), then a cheap precondition function in `_PRECONDITIONS` (e.g. `_inbox_has_new_files`) that skips dispatch — and burns no LLM tokens — when an agent has no pending work.
3. `_load_agent_dispatch()` reads the task's `agent.json`; if missing/incomplete it falls back to `registry.yaml`'s `default_dispatch` (see `docs/specs/agents/agent-dispatch-settings.md`).
4. Dispatch type (`cli` / `claude-api` / `claude-code` / `openai-api` / `gemini-api` / `openrouter-api` / `lm-studio` / `codex-cli`) selects a runner from `nexus/shared/runners/` via `get_runner()`. A per-task `fallback_dispatch` retries on non-zero exit. Static tasks dispatch as `cli` with args `["-m", "nexus.tasks.<module>"]`.
5. On success, `commit_changes()` stages only the paths in the agent's `AGENT.md` `commit_scope:` block and commits — agents never commit their own changes.
6. Metrics (`state/agent-metrics.json`), token costs (`state/costs/`), and per-task/master logs (`state/logs/`) are recorded every cycle regardless of outcome.

**Agent contract** (`nexus/shared/interfaces.py`, `nexus/shared/models.py`): every agent subclasses `BaseAgent` (`bootstrap()` → `run_batch()` → default `execute()` lifecycle logging START/DONE), and each pipeline concern (LLM client, state store, frontmatter I/O, vault guard, quality gate, wikilink resolver, etc.) is an `I*` Protocol/ABC in `interfaces.py` with a concrete implementation under the owning agent's `tools/`. Read the relevant `docs/specs/agents/agent-*.spec.md` before touching an agent — it is the source of truth for that agent's contract, not the code.

**Each agent folder** (`agents/<name>/`) has: `agent.json` (task ids, `intervalSeconds`, dispatch config), `AGENT.md` (purpose, inputs/outputs, `commit_scope:`, restrictions — read before modifying), `state/` (gitignored runtime state, JSON files with atomic tmp-rename writes), and — LLM agents only — `prompts/system.md` + `tools/<name>_agent.py`. Static task code lives in `system/src/nexus/tasks/` instead. Adding a new automation means creating these plus a `state/tasks-state.json` entry — see "Adding a New Automation" below.

**Security boundary** (`nexus/shared/vault_guard.py`, `IVaultGuard`): agents must call `assert_writable()` / `assert_not_self_approved()` before any frontmatter write. `status: approved` and `reviewed: true` are human-only fields — no agent may set them. `02-Library/` is never written by agents directly; only humans promote drafts there from `01-Processing/`.

## Vault Purpose

Dungeon Master Nexus Campaigns. Transforms raw inspiration into reusable campaign assets via AI processing + human review.

Root: `.knowledge-base`

> Every agent reads `AGENTS.md` before making changes. It is the operating system of this vault.

---

## Folder Structure

| Folder | Purpose | Rules |
|--------|---------|-------|
| `00-Inbox/` | Raw unprocessed material (images, PDFs, voice notes) | Never modify. Never delete. Preserve original filenames. |
| `01-Processing/` | AI-generated drafts pending human review | Provisional. Human approval required before promotion. |
| `02-Library/` | Approved canon knowledge (NPCs, locations, factions, lore) | Only approved content. Must have metadata + relationships. |
| `03-Campaigns/` | Campaign-specific material | Reference Library entities. Use links, not duplicates. |
| `04-Relationships/` | Generated knowledge graphs (timelines, faction maps) | Auto-generated. Do not edit manually. |
| `05-Assets/` | Approved media (portraits, tokens, maps, handouts) | Must link to entities. Unused assets stay in Processing. |
| `99-Archive/` | Retired content | Never delete approved content — archive instead. |

### 00-Inbox/ subfolders
- `00-Inbox/images/` — campaign art, organized by arc (A1 Annûn, A2, A5 Cirit, etc.)
- `00-Inbox/docs/` — world building documents
- `00-Inbox/songs/` — ambient music references
- `00-Inbox/tokens/` — token frames and molduras

---

## Pipeline Workflow

```
00-Inbox  →  01-Processing  →  (human review)  →  02-Library
                                                        ↓
                                                   03-Campaigns
                                                   04-Relationships
                                                   05-Assets
```

1. Drop sources into `00-Inbox/` — treat as read-only
2. Automation agents process `00-Inbox/` and write drafts to `01-Processing/`
3. Human reviews drafts, sets `status: approved` + `quality: N`
4. Approved content promoted to `02-Library/` (or `03-Campaigns/`, `05-Assets/`)
5. Relationships auto-indexed into `04-Relationships/`

---

## Metadata Standard

Every entity in `02-Library/` must include:

```yaml
---
id: npc-necromancer-black-hollow
type: npc
status: approved
quality: 8
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags:
  - undead
  - villain
source:
  - necromancer_001.png
reviewed: true
relationships:
  - "[[location-black-hollow-cemetery]]"
  - "[[faction-cult-of-undying]]"
---
```

### Allowed `type` values
`npc` · `character` · `faction` · `location` · `city` · `village` · `dungeon` · `item` · `artifact` · `quest` · `encounter` · `creature` · `monster` · `event` · `religion` · `organization` · `timeline` · `lore`

### Quality scores
| Score | Meaning |
|-------|---------|
| 1–3 | Low quality — reject |
| 4–6 | Needs review |
| 7–8 | Good |
| 9–10 | Library candidate |

Only `quality >= 7` may enter `02-Library/`.

---

## Naming Convention

Slug format: `{type}-{descriptors}.md`

```
npc-necromancer-black-hollow.md
quest-missing-villagers.md
location-black-hollow-cemetery.md
battlemap-dungeon-01.md
```

Avoid: `final_v2.md`, `newnpc.md`, `coolidea.md`

---

## Wikilinks

Use `[[slug-name]]` for internal links. Match exact filename without extension.

Every entity must link to at least one other entity. No orphans.

Preferred relationships:
- NPC → location, faction, quest
- Quest → NPC, location, reward item
- Location → NPC, faction, quest
- Faction → NPC, location

---

## Automation Scripts (`system/`)

### Path conventions
| Variable | Path |
|----------|------|
| Inbox images | `$VaultRoot\00-Inbox\images` |
| Processing dir | `$VaultRoot\01-Processing` |
| Token moldura | `05-Assets\tokens\frames\frame.png` |

### Encoding
All file I/O **must** use `-Encoding UTF8` explicitly. Never rely on PS default encoding.

### Logging

| Destination | Path | Purpose |
|-------------|------|---------|
| Shared log | `system/logs/automation.log` | Full consolidated history |
| Per-task log | `system/logs/<script-name>_YYYY-MM-DD.log` | Per-script daily rotation |

Log line format: `[YYYY-MM-DD HH:mm:ss] [<task-id>] <message>`

Every script must emit `--- START ---` and `--- DONE ---` markers via `Write-Log`.

### Adding a New Automation
Static (no LLM):
1. Create `system/src/nexus/tasks/<name>.py` (plain script with a `main()`)
2. Create `agents/<name>/agent.json` with `tasks.<task-id>.intervalSeconds`, `.description`, and cli dispatch: `{"command": "python", "args": ["-m", "nexus.tasks.<name>"]}`
3. Add the task to `_AGENT_JSON_SPECS` in `system/src/nexus/tasks/repair_agent.py` (agent.json is gitignored; repair scaffolds it on fresh clones)

LLM-driven:
1. Create `agents/<name>/tools/<name>_agent.py` with `TOOLS` list and `call_tool()` function
2. Create `agents/<name>/agent.json` with `tasks.<task-id>.intervalSeconds`, `.description`, and `dispatch.claude_api` config
3. Create `agents/<name>/prompts/system.md` with agent role, tools, and success criteria

Both: add entry to `agents/runtime/state/tasks-state.json` with `lastRun: "1970-01-01T00:00:00Z"`

### Task Intervals
- `3600` — hourly (cleanup, compile, classify, generate)
- `86400` — daily (remove-emoji-filenames)

---

## Working Conventions

- Do NOT create new notes unless explicitly asked
- When adding connections: add relationships field + `## Related` section with wikilinks
- Authors are always wikilinked: `[[Author Name]]`
- Dates use ISO format: YYYY-MM-DD
- Agents may recommend quality scores but may never self-approve content
- Canon content must not be modified without explicit human action

---

## OpenWiki

This repository has documentation located in the `/openwiki` directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.
