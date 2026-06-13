# Claude Code — Nexus Campaigns

## Vault Purpose

Dungeon Master Nexus Campaigns. Transforms raw inspiration into reusable campaign assets via AI processing + human review.

Root: `knowledge-base`

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

## Automation Scripts (`.system/`)

### Path conventions
| Variable | Path |
|----------|------|
| Inbox images | `$VaultRoot\00-Inbox\images` |
| Processing dir | `$VaultRoot\01-Processing` |
| Token moldura | `00-Inbox\tokens\Molduras\moldura_default.png` |

### Encoding
All file I/O **must** use `-Encoding UTF8` explicitly. Never rely on PS default encoding.

### Logging

| Destination | Path | Purpose |
|-------------|------|---------|
| Shared log | `.system/logs/automation.log` | Full consolidated history |
| Per-task log | `.system/logs/<script-name>_YYYY-MM-DD.log` | Per-script daily rotation |

Log line format: `[YYYY-MM-DD HH:mm:ss] [<task-id>] <message>`

Every script must emit `--- START ---` and `--- DONE ---` markers via `Write-Log`.

### Adding a New Automation
1. Create `.agents/<name>/tools/<name>_agent.py` with `TOOLS` list and `call_tool()` function
2. Create `.agents/<name>/agent.json` with `tasks.<task-id>.intervalSeconds`, `.description`, and `dispatch.claude_api` config
3. Create `.agents/<name>/prompts/system.md` with agent role, tools, and success criteria
4. Add entry to `.agents/runtime/state/tasks-state.json` with `lastRun: "1970-01-01T00:00:00Z"`

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
