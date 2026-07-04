---
name: wiki
purpose: >
  Compiles raw 00-Inbox/ markdown notes into structured AGENTS.md-compliant DM entity
  drafts in 01-Processing/. Reads inbox-queue.json for document entries with
  agents.wiki=pending. Uses LocalRouter LLM with full canon context from 02-Library/
  to generate description, details, hooks, and wikilinks. Marks agents.wiki=done in
  inbox-queue.json after each successful write.
inputs:
  - state://system/state/inbox-queue.json  (type=document, agents.wiki=pending)
  - vault://02-Library/**/*.md              (read-only: canon context, id/type/tags/rels, up to 50 entities)
  - state://bad-wiki-docs.txt
  - LLM: http://localhost:8080/v1/chat/completions (LocalRouter, model: auto)
outputs:
  - vault://01-Processing/{slug}.md (structured entity draft)
  - state://system/state/inbox-queue.json (agents.wiki=done per processed entry)
  - state://bad-wiki-docs.txt (rejected/failed source paths appended)
  - state://logs/compile_wiki_YYYY-MM-DD.log
dependencies:
  - ingestion (populates inbox-queue.json with type=document entries)
dispatch_config: agent.json
owned_tools:
  - tools/compile_wiki.py
responsibilities:
  - Pre-flight check LocalRouter at localhost:8080 before processing
  - Load inbox-queue.json and filter for type=document, agents.wiki=pending entries
  - Skip entries already in bad-wiki-docs.txt
  - Load 02-Library/ canon entity list (id, type, tags, relationships) as context string
  - Read each pending document file from the path stored in inbox-queue.json
  - Strip HTML tags/styles/scripts from DOCX-converted files before LLM call
  - Skip files under 100 chars (even after HTML stripping) — mark agents.wiki=done, not bad
  - Truncate content to 6000 chars with truncation notice
  - Call LLM with DM synthesis prompt enforcing AGENTS.md frontmatter schema
  - Enforce post-LLM: status=draft, reviewed=false, quality=0, source=[filename]
  - Validate type field against allowed types; default to lore if invalid
  - Write output to 01-Processing/{slug}.md; add date suffix if file already exists
  - Mark agents.wiki=done in inbox-queue.json after successful write
  - Mark failures in bad-wiki-docs.txt (read errors, repeated LLM failures)
  - Abort batch on connection error (will retry next run, do not mark file bad)
  - 2000ms sleep between LLM calls
  - Process up to 5 documents per run (BATCH_SIZE)
restrictions:
  - Must not process files in 02-Library/
  - Must not set reviewed: true in any output
  - Must not set status: approved or status: review in any output
  - Must not approve content or modify metadata standards
  - Must not modify 02-Library/
  - Must not process queue entries with type != document
  - LLM max_tokens: 1500; temperature: 0.3
state_files:
  - system/state/inbox-queue.json
  - agents/wiki/state/bad-wiki-docs.txt
commit_scope:
  - knowledge-base/01-Processing
---
