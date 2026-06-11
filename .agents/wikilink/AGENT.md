---
name: wikilink
purpose: >
  Inserts cross-reference wikilinks into the ## Related section of approved
  02-Library/ entities. Resolves links by matching entity slugs across the
  library and injecting [[slug]] references where missing. No LLM calls.
inputs:
  - vault://02-Library/**/*.md
  - state/wikilink-state.json
outputs:
  - vault://02-Library/**/*.md (## Related section updated in-place)
  - state/wikilink-state.json (processed file paths and link counts)
  - state/logs/14-wikilink-library_YYYY-MM-DD.log
dependencies:
  - ingestion
dispatch_config: agent.json
owned_tools:
  - tools/wikilink_library.py
responsibilities:
  - Collect all entity slugs from 02-Library/ (filename stems)
  - For each .md in 02-Library/: parse frontmatter + body
  - Score entity pairs by shared tags, slug mentions, and keyword overlap
  - Insert missing [[slug]] wikilinks into ## Related section (create if absent)
  - Never duplicate existing wikilinks
  - Write updated file atomically (tmp → replace)
  - Track processed files in state/wikilink-state.json
  - Batch: 20 files per run
restrictions:
  - Must not call any LLM
  - Must not modify 00-Inbox/ or 01-Processing/
  - Must not modify frontmatter
  - Must not create new files
  - Must not remove existing wikilinks
state_files:
  - state/wikilink-state.json
commit_scope:
  - knowledge-base/02-Library
  - .agents/wikilink/state
---
