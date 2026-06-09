---
name: wiki
purpose: >
  Compiles raw 00-Inbox/ markdown notes into structured AGENTS.md-compliant DM entity
  drafts in 01-Processing/. Uses LocalRouter LLM with full canon context from 02-Library/
  to generate description, details, hooks, and wikilinks. Tracks processed files to
  avoid reprocessing.
inputs:
  - vault://00-Inbox/**/*.md
  - vault://02-Library/**/*.md (read-only: canon context, up to 50 entities)
  - state/processed.txt
  - state/bad-wiki-docs.txt
  - LLM: http://localhost:8080/v1/chat/completions (LocalRouter, model: auto)
outputs:
  - vault://01-Processing/{slug}.md (structured entity draft)
  - state/processed.txt (processed source paths appended)
  - state/bad-wiki-docs.txt (rejected/failed source paths appended)
  - state/logs/03-compile-wiki_YYYY-MM-DD.log
dependencies:
  - ingestion
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: auto @ localhost:8080
  fallbacks: []
owned_tools:
  - tools/03-compile-wiki.ps1
responsibilities:
  - Pre-flight check LocalRouter at localhost:8080 before processing
  - Load processed.txt and bad-wiki-docs.txt skip lists
  - Load 02-Library/ canon entity list (id + type) as context string
  - Scan 00-Inbox/ recursively for .md files not in skip lists
  - Skip files under 100 chars (even after HTML stripping)
  - Strip HTML tags/styles/scripts from DOCX-converted files before LLM call
  - Truncate content to 6000 chars with truncation notice
  - Call LLM with DM synthesis prompt enforcing AGENTS.md frontmatter schema
  - Prompt requires: id (type-slug), type from valid list, status: draft, quality: 0, reviewed: false
  - Prompt requires sections: Description, Details, Hooks, Related with wikilinks
  - Write output to 01-Processing/{slug}.md; add date suffix if file already exists
  - Mark processed in processed.txt; mark failures in bad-wiki-docs.txt
  - Abort batch on connection error (will retry next run, do not mark file bad)
  - 2000ms sleep between LLM calls
restrictions:
  - Must not process files in 02-Library/
  - Must not set reviewed: true in any output
  - Must not approve content or modify metadata standards
  - Must not modify 02-Library/
  - LLM max_tokens: 1500; temperature: 0.3
state_files:
  - state/processed.txt
  - state/bad-wiki-docs.txt
---
