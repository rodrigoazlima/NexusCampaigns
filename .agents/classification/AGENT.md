---
name: classification
purpose: >
  Enriches .md files in 00-Inbox/ and 01-Processing/ with DM-domain tags and entity
  type inference via LocalRouter LLM. Detects potential duplicates against 02-Library/
  slugs. Modifies frontmatter in-place. Only processes files with 5 or fewer existing
  tags or missing type field.
inputs:
  - vault://00-Inbox/**/*.md
  - vault://01-Processing/**/*.md
  - vault://02-Library/**/*.md (read-only: slug list for dedup check)
  - state/bad-docs.txt
  - LLM: http://localhost:8080/v1/chat/completions (LocalRouter, model: auto)
outputs:
  - vault://00-Inbox/**/*.md (frontmatter updated in-place)
  - vault://01-Processing/**/*.md (frontmatter updated in-place)
  - state/bad-docs.txt (failed files appended)
  - state/logs/04-enrich-tags_YYYY-MM-DD.log
dependencies:
  - ingestion
  - wiki
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: auto @ localhost:8080
  fallbacks: []
owned_tools:
  - tools/04-enrich-tags.ps1
responsibilities:
  - Pre-flight check LocalRouter at localhost:8080 before processing
  - Load bad-docs.txt skip list on startup
  - Load 02-Library/ slug list once per run for dedup comparison
  - For each .md in 00-Inbox/ and 01-Processing/: parse YAML frontmatter
  - Skip files in bad-docs.txt
  - If tags count <= 5: call tag LLM with title + 500-char body snippet
  - If type field missing: call type inference LLM with title + snippet
  - Validate LLM tag output against 29-tag allowed list
  - Validate type against 18-type allowed list
  - Compare slug against library slugs (exact lowercase match) → inject duplicate_of field
  - Merge new tags with existing (deduplicated); rebuild frontmatter
  - Write updated file with 5-retry loop (handles lock contention)
  - Add to bad-docs.txt on parse failure or persistent LLM failure
  - 300ms sleep between file writes
restrictions:
  - Must not approve content
  - Must not create canon entries
  - Must not modify 02-Library/ files
  - Must not remove existing tags (only add/merge)
  - Tag LLM max 80 tokens; type LLM max 10 tokens
state_files:
  - state/bad-docs.txt
commit_scope:
  - knowledge-base/00-Inbox
  - knowledge-base/01-Processing
  - .agents/classification/state
  - .shared/state
---

## Valid Tags (29)
npc · creature · monster · location · dungeon · city · village · faction · quest · encounter · item · artifact · lore · religion · event · organization · timeline · undead · dark · fire · light · none · portrait · battlemap · scene · token · images · pathfinder2e

## Valid Types (18)
npc · character · faction · location · city · village · dungeon · item · artifact · quest · encounter · creature · monster · event · religion · organization · timeline · lore
