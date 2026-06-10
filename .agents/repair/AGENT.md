---
name: repair
purpose: >
  Maintenance agent. Detects and fixes stale lock files, ensures required state
  directories exist, and removes orphan image references from state indexes.
  No LLM calls. No vault content changes.
inputs:
  - .agents/runtime/state/runner.lock
  - .agents/*/state/**
  - .shared/state/inbox-queue.json
outputs:
  - .agents/runtime/state/ (stale lock removed)
  - .agents/*/state/ (missing dirs created)
  - state/logs/12-repair-agent_YYYY-MM-DD.log
dependencies: []
dispatch_config: agent.json
owned_tools:
  - tools/repair_agent.py
responsibilities:
  - Remove runner.lock if older than 1800 seconds (stale)
  - Ensure all directories listed in shared.defaults.REQUIRED_DIRS exist
  - Remove inbox-queue.json entries whose source file no longer exists in 00-Inbox/
  - Remove processed-images.json entries whose file no longer exists
restrictions:
  - Must not call any LLM
  - Must not modify 02-Library/
  - Must not delete source files from 00-Inbox/
  - Must not modify vault content files (.md, images)
state_files:
  - state/logs/12-repair-agent_YYYY-MM-DD.log
commit_scope:
  - .agents/runtime/state
  - .agents/ingestion/state
  - .agents/vision/state
  - .agents/lore/state
  - .agents/token/state
  - .agents/classification/state
  - .agents/wiki/state
  - .agents/review/state
  - .agents/repair/state
  - .agents/wikilink/state
  - .shared/state
---
