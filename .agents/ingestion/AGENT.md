---
name: ingestion
purpose: >
  First-stage pipeline agent. Normalizes filenames in 00-Inbox/, converts DOCX to
  Markdown via Pandoc, registers all new Inbox files into .system/state/inbox-queue.json
  with agent processing slots initialized. No LLM calls.
inputs:
  - vault://00-Inbox/**
  - .system/state/inbox-queue.json
  - state/processed-docx.txt
outputs:
  - .system/state/inbox-queue.json (new entries written)
  - vault://00-Inbox/ (renamed files, emoji stripped)
  - vault://00-Inbox/images/{slug}/ (extracted DOCX images)
  - state/processed-docx.txt
  - state/logs/11-ingestion-agent_YYYY-MM-DD.log
dependencies: []
dispatch_config: agent.json
owned_tools:
  - tools/11-ingestion-agent.ps1
responsibilities:
  - Strip emoji from filenames in 00-Inbox/ using Unicode range pattern (idempotent)
  - Resolve filename collision by appending timestamp to stem
  - Discover unprocessed .docx files vault-wide (exclude .git and .agents)
  - Install Pandoc via winget if missing
  - Convert each DOCX to GFM Markdown with --extract-media flag
  - Flatten Pandoc media subdirectory and fix image paths in output markdown
  - Mark converted DOCX paths in state/processed-docx.txt to skip on next run
  - Scan 00-Inbox/ recursively for all files not in inbox-queue.json
  - Assign type (image/document/other) based on file extension
  - Initialize agent slots: image → vision+lore+classification pending; document → wiki+classification pending; other → all skip
  - Persist queue atomically using ConvertTo-Json -Depth 5
restrictions:
  - Must not call any LLM
  - Must not modify 02-Library/
  - Must not delete source files from 00-Inbox/
  - Must not rename files outside 00-Inbox/
  - DOCX batch capped at 10 per run
state_files:
  - state/processed-docx.txt
  - .system/state/inbox-queue.json (shared owner — ingestion writes, others update)
commit_scope:
  - knowledge-base/00-Inbox
---
