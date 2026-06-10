# Agent Spec — Wiki

**Trigger:** hourly  
**Input:** `00-Inbox/` markdown documents (`document` entries in `.shared/state/inbox-queue.json` with `agents.wiki = pending`)  
**Output:** synthesized entity pages in `01-Processing/`  
**Dispatch:** `claude-api` · `claude-sonnet-4-6` · `tools_module: wiki.tools.compile_wiki`  
**Dependency:** LocalRouter at `http://localhost:8080` (text LLM)

---

## Responsibilities

1. **Load canon context** — load approved entities from `02-Library/` (id, type, tags, relationships) as LLM context to prevent contradictions.
2. **Scan pending docs** — read `.shared/state/inbox-queue.json` for entries with `type: document` and `agents.wiki: pending`.
3. **Synthesize entity page** — for each pending document, call text LLM with the raw content and canon context to produce a structured entity page.
4. **Write draft** — write `01-Processing/{slug}.md` following the AGENTS.md-compliant frontmatter standard.
5. **Mark queue done** — set `agents.wiki = done` in `.shared/state/inbox-queue.json`.

---

## Input: Document Types Handled

Documents from `00-Inbox/` converted by Ingestion Agent (Markdown from `.docx`, raw `.md` notes):

| Content type | Expected output entity type |
|---|---|
| NPC description note | `npc` |
| Location description | `location` or `city` or `dungeon` |
| Faction/organization note | `faction` or `organization` |
| Lore/history note | `lore` or `event` or `timeline` |
| Item/artifact note | `item` or `artifact` |

---

## Output: Draft Frontmatter

```yaml
---
id: {type}-{slug}
type: npc | location | faction | lore | item | ...
status: draft
quality: 0
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags:
  - tag1
source:
  - original-doc-filename.md
reviewed: false
relationships: []
---
```

---

## Constraints

- Cannot approve content (`reviewed: false` always on write)
- Cannot modify `02-Library/`
- Cannot process `image` or `other` queue entries (only `document`)
- Batch size: 5 documents per run
