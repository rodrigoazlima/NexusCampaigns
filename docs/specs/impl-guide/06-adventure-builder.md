# Impl: Adventure Builder Agent

**Phase:** P4  
**Priority:** Medium  
**Effort:** 4 days  
**Depends on:** Curator (P2), Relationship agent (existing stub), Canon Validator (P2)

---

## Problem

All upstream pipeline work (NPC generation, classification, wiki compilation, relationships) feeds into `02-Library/` but nothing synthesises it into usable campaign output. The DM must manually read dozens of entity files and assemble an adventure by hand. The `adventure-builder` AGENT.md stub exists but has no implementation.

This agent is the highest-value output of the entire system. Every entity in the Library becomes valuable only when it is woven into a playable arc.

---

## Goal

The Adventure Builder reads a seed file specifying arc parameters (arc code, tone, hooks, key NPCs, required locations), scans `02-Library/` for matching entities, traverses the relationship graph, and produces a structured adventure module in `03-Campaigns/{arc}/`. The output is a draft — it never becomes canon and is never promoted to `02-Library/`.

---

## Inputs

1. **Arc seed file:** `03-Campaigns/{arc}/seed.yaml` — human-authored parameters (see format below)
2. **Canon entities:** `02-Library/` — NPCs, locations, factions, quests, items with status: approved
3. **Relationship graph:** `04-Relationships/` — pre-computed entity adjacency (if Relationship agent has run)
4. **Existing sessions:** `03-Campaigns/{arc}/sessions/` — past session notes to avoid repetition

---

## Arc Seed File Format

Human creates `03-Campaigns/A1-Annun/seed.yaml`:

```yaml
arc: A1-Annun
title: "The Fall of Annûn"
tone: dark-heroic          # dark-heroic | mystery | exploration | political | horror
target_sessions: 6         # how many sessions this arc should span
party_level: 3
required_npcs:             # must appear in this arc
  - npc-elder-annun
  - npc-blacksmith-cirit
required_locations:
  - location-city-annun
  - location-cursed-forest
forbidden_entities:        # must NOT appear (spoilers, future arcs)
  - npc-villain-final-boss
hooks:
  - "The party arrives as refugees seeking shelter"
  - "A merchant has gone missing on the road from Cirit"
constraints:
  - "No resurrection magic exists in this world"
  - "The local guard is corrupt but not openly hostile"
```

If `seed.yaml` does not exist for an arc: agent skips. Adventure builder is seed-driven, not automatic.

---

## Output Format

`03-Campaigns/A1-Annun/adventure-module.md`:

```markdown
---
arc: A1-Annun
title: The Fall of Annûn
generated: 2026-06-10
status: draft
quality: 0
reviewed: false
---

# The Fall of Annûn — Adventure Module

## Overview
[2-3 paragraph arc summary]

## Key Entities
### NPCs
- [[npc-elder-annun]] — role in arc, motivations
- [[npc-blacksmith-cirit]] — role in arc, how they connect to hooks

### Locations
- [[location-city-annun]] — opening location, description for DM
- [[location-cursed-forest]] — Act 2 centerpiece

### Factions
- [[faction-city-guard]] — opposition force

## Act Structure

### Act 1: Arrival
**Hook:** [from seed.yaml hook 1]
**Scenes:**
1. Scene name — brief DM description, key choices
2. ...

### Act 2: Complication
...

### Act 3: Resolution
...

## Encounter Seeds
- Encounter concept 1 — location, participants, stakes
- Encounter concept 2

## Open Threads
[Unresolved hooks for future arcs]

## DM Notes
[Tone guidance, pacing notes, potential player directions]
```

---

## Scope

Files to create:
- `.agents/adventure-builder/agent.json`
- `.agents/adventure-builder/tools/__init__.py`
- `.agents/adventure-builder/tools/adventure_builder_agent.py`
- `.agents/adventure-builder/prompts/system.md`
- `.agents/tests/test_adventure_builder.py`

Files to modify:
- `.agents/adventure-builder/AGENT.md` — fill in empty stub

---

## `agent.json`

```json
{
  "tasks": {
    "adventure-builder-agent": {
      "intervalSeconds": 86400,
      "description": "Synthesise canon entities into adventure module drafts for arcs with seed.yaml",
      "dispatch": {
        "type": "claude-api",
        "claude_api": {
          "model": "claude-sonnet-4-6",
          "system_file": "prompts/system.md",
          "tools_module": "adventure-builder.tools.adventure_builder_agent",
          "history_file": "adventure-builder-history.json",
          "max_tokens": 8192,
          "timeout_seconds": 900,
          "max_tool_rounds": 40
        }
      }
    }
  }
}
```

Higher `max_tokens` (8192) and longer `timeout_seconds` (900) because adventure modules are long documents with many entity reads.

---

## Tools

### `list_arc_seeds() → list[ArcSeed]`

Scans `03-Campaigns/*/seed.yaml`. Returns parsed seeds for arcs that:
- Have `seed.yaml` present
- Do NOT already have `adventure-module.md` with `status != "draft"` (i.e., human has approved it — don't regenerate)
- All `required_npcs` and `required_locations` exist in `02-Library/`

```python
@dataclass
class ArcSeed:
    arc: str
    seed_path: Path
    campaigns_dir: Path
    params: dict          # raw seed.yaml contents
    missing_entities: list[str]  # required entities not found in library
```

If `missing_entities` is non-empty: log warning and skip arc (canon incomplete).

### `read_entity(slug: str) → EntityContent`

Reads a single `02-Library/{slug}.md` file. Returns frontmatter + body + wikilinks.

```python
@dataclass
class EntityContent:
    slug: str
    frontmatter: dict
    body: str
    wikilinks: list[str]   # outbound [[links]] from this entity
```

### `get_neighbors(slug: str, depth: int = 1) → list[str]`

Reads `04-Relationships/` index files (if they exist) to find entities connected to `slug` within `depth` hops. Falls back to scanning `read_entity(slug).wikilinks` if relationship index absent.

Used to discover relevant entities beyond the seed's required list — e.g., if the seed requires `npc-elder-annun`, neighbors might surface `faction-council-annun` and `location-elder-hall`.

### `list_existing_sessions(arc: str) → list[str]`

Reads `03-Campaigns/{arc}/sessions/*.md`. Returns slugs of covered content (NPCs appeared in, locations visited) to avoid redundancy in new module.

### `write_adventure_module(arc: str, content: str) → None`

Writes `03-Campaigns/{arc}/adventure-module.md`. Always `status: draft`, `reviewed: false`.

Checks: if `adventure-module.md` already exists with human-set `status: approved` → SKIP (never overwrite approved output).

### `write_log(arcs_processed: int, arcs_skipped: int, failed: int) → None`

Standard log format.

---

## System Prompt (`.agents/adventure-builder/prompts/system.md`)

```markdown
# Adventure Builder Agent

You are the Adventure Builder for a Dungeon Master knowledge vault.
Your role: synthesise approved canon entities into a structured adventure module for each arc that has a seed file.

## Workflow

1. Call `list_arc_seeds` — find arcs with seed.yaml that need a module
2. For each arc:
   a. Call `read_entity` for each required NPC, location, faction in the seed
   b. Call `get_neighbors` on key entities to discover connected canon
   c. Call `list_existing_sessions` to understand what has already been played
   d. Synthesise an adventure module using the entities, seed params, and prior sessions
   e. Call `write_adventure_module` with the completed module
3. Call `write_log`

## Rules

- Only use entities from 02-Library/ with status: approved
- Never invent entities not in the library — reference what exists
- Respect forbidden_entities from seed — they must not appear
- Sessions already played must not be repeated — check list_existing_sessions
- Output is a draft (status: draft, reviewed: false) — never canon
- Structure output per the adventure module format spec
- If required entities are missing from 02-Library/, skip the arc and log a warning
- Arc tone must match the `tone` field from seed.yaml
- target_sessions from seed should guide act structure depth
```

---

## Adventure Module Quality

Adventure modules do NOT go through QualityGate (which is for entity metadata). They go directly to `03-Campaigns/` as drafts. Human DM reviews and uses them directly, or promotes to `03-Campaigns/{arc}/approved-module.md`.

The Curator agent does NOT process `03-Campaigns/` — Curator only handles `01-Processing/ → 02-Library/`.

---

## Tests

`.agents/tests/test_adventure_builder.py`:

```python
def test_skips_arc_without_seed(tmp_path):
    # Arc dir exists but no seed.yaml
    # Assert: not included in list_arc_seeds result

def test_skips_arc_with_missing_required_entities(tmp_path):
    # seed.yaml requires npc-A but npc-A not in 02-Library/
    # Assert: arc in result but missing_entities=[npc-A]

def test_skips_approved_existing_module(tmp_path):
    # adventure-module.md exists with status: approved
    # Assert: arc not returned by list_arc_seeds

def test_get_neighbors_falls_back_to_wikilinks(tmp_path):
    # No 04-Relationships/ index
    # Entity has [[npc-linked]] in body
    # Assert: get_neighbors returns ["npc-linked"]

def test_write_adventure_module_never_overwrites_approved(tmp_path):
    # Existing approved module
    # Call write_adventure_module
    # Assert: existing file unchanged

def test_write_adventure_module_draft_metadata(tmp_path):
    # Call write_adventure_module
    # Assert: status=draft, reviewed=false in output frontmatter
```

---

## Success Criteria

- Adventure module generated for each arc that has `seed.yaml` and complete required entities in library.
- Module uses only approved canon entities — no invented content.
- Forbidden entities from seed never appear in output.
- Previously played sessions are not repeated in new module.
- Output is always `status: draft`, `reviewed: false` — never canon.
- Approved existing modules are never overwritten.
- Agent handles missing `04-Relationships/` gracefully (fallback to wikilink traversal).
