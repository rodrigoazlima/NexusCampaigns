# Agent Spec — Classification

**Trigger:** hourly  
**Input:** notes in `00-Inbox/` and `01-Processing/` with ≤5 tags; `system/state/inbox-queue.json`  
**Output:** enriched frontmatter in-place  
**Dependency:** LocalRouter at `http://localhost:8080`  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: classification.tools.enrich_tags`

---

## Responsibilities

1. Assign DM-domain tags to notes with sparse tagging.
2. Infer `type:` field if missing.
3. Flag potential duplicates against `02-Library/` by slug similarity.

---

## Allowed Tags

`npc` · `creature` · `monster` · `location` · `dungeon` · `city` · `village` · `faction` · `quest` · `encounter` · `item` · `artifact` · `lore` · `religion` · `event` · `organization` · `timeline` · `undead` · `dark` · `fire` · `light` · `none` · `portrait` · `battlemap` · `scene` · `token` · `images` · `pathfinder2e`

---

## Constraints

- Cannot approve content
- Cannot create canon
- Cannot modify `02-Library/`
