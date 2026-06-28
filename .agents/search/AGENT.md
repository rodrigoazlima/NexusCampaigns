---
name: search
purpose: >
  Builds and maintains a keyword + tag search index over 02-Library/ and
  01-Processing/ entities. Writes search-index.json. Answers DM queries
  by filtering the index and returning ranked SearchEntry results with
  wikilink citations. No LLM calls — pure text matching.
inputs:
  - vault://02-Library/**/*.md
  - vault://01-Processing/**/*.md
  - .agents/search/state/search-index.json
outputs:
  - .agents/search/state/search-index.json
  - state/logs/search_YYYY-MM-DD.log
dependencies:
  - ingestion
  - classification
dispatch_config: agent.json
owned_tools:
  - tools/search_agent.py
responsibilities:
  - Scan 02-Library/ and 01-Processing/ via EntityScanner
  - Build SearchIndexState: one SearchEntry per entity with id, type, title, tags, relationships, status, quality, body_excerpt (first 200 chars of body)
  - Write index to search-index.json atomically
  - On query: filter entries by keyword (id, title, body_excerpt, tags) and optional tag list
  - Return results sorted by quality DESC, then updated DESC
  - Batch: full rebuild per run (no incremental update in v1)
restrictions:
  - Read-only on all vault directories
  - Must not call any LLM
  - Must not modify frontmatter
state_files:
  - state/search-index.json
  - state/logs/search_YYYY-MM-DD.log
commit_scope:
  # none — agent produces no knowledge-base content; must not auto-commit
---
