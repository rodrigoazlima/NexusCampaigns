---
name: canon
purpose: >
  Validates consistency of approved entities in 02-Library/ against each other.
  Detects broken wikilinks, missing required fields, duplicate IDs, orphan entities
  (no relationships), and contradiction flags. Produces a CanonReport. Read-only
  on all vault directories — never modifies content.
inputs:
  - vault://02-Library/**/*.md
  - .agents/canon/state/canon-report-latest.json
outputs:
  - .agents/canon/state/canon-report-latest.json
  - .agents/canon/state/reports/canon-{YYYY-MM-DD}.json
  - state/logs/canon_YYYY-MM-DD.log
dependencies: []
dispatch_config: agent.json
owned_tools:
  - tools/canon_agent.py
responsibilities:
  - Scan all .md files in 02-Library/ via EntityScanner
  - Build slug index (filename stem → path) for wikilink resolution
  - For each entity:
    - Validate required frontmatter fields (id, type, status, quality, reviewed, relationships)
    - Resolve each [[wikilink]] in relationships against slug index; flag broken ones
    - Flag entities with empty relationships list as orphan_entity
    - Check id uniqueness; flag duplicate_id violations
    - Check quality >= 7 and reviewed=true (warn if approved entity fails this)
  - Write CanonReport to canon-report-latest.json and dated archive
  - Emit START/DONE log markers via shared Logger
restrictions:
  - Read-only on 02-Library/ — must never write to vault directories
  - Must not modify any approved entity without explicit human action
  - Must not call any LLM
state_files:
  - state/canon-report-latest.json
  - state/reports/
  - state/logs/canon_YYYY-MM-DD.log
commit_scope:
  - .agents/canon/state
---
