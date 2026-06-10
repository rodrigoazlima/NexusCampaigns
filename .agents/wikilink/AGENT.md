---
name: wikilink
purpose: >
  Inserts cross-reference wikilinks into the ## Related section of approved
  02-Library/ entities. Resolves links by matching entity slugs across the
  library and injecting [[slug]] references where missing. No LLM calls.
inputs:
  - vault://02-Library/**/*.md
  - state/processed-wikilinks.txt
outputs:
  - vault://02-Library/**/*.md (## Related section updated in-place)
  - state/processed-wikilinks.txt (processed file paths appended)
  - state/logs/14-wikilink-library_YYYY-MM-DD.log
dependencies:
  - ingestion
dispatch_config: agent.json
owned_tools:
  - tools/wikilink_library.py
responsibilities:
  - Collect all entity slugs from 02-Library/ (filename stems)
  - For each .md in 02-Library/: parse frontmatter + body
  - Identify unlinked slug mentions in ## Related section
  - Insert missing [[slug]] wikilinks without duplicating existing ones
  - Write updated file with 3-retry loop
  - Track processed files in state/processed-wikilinks.txt
  - Batch: 20 files per run
restrictions:
  - Must not call any LLM
  - Must not modify 00-Inbox/ or 01-Processing/
  - Must not change frontmatter fields other than relationships
  - Must not create new files
  - Must not remove existing wikilinks
state_files:
  - state/processed-wikilinks.txt
commit_scope:
  - knowledge-base/02-Library
  - .agents/wikilink/state
---
