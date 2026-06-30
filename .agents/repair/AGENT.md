---
name: repair
purpose: >
  Maintenance agent. Detects and fixes stale lock files, ensures required state
  directories exist, and removes orphan image references from state indexes.
  No LLM calls. No vault content changes.
inputs:
  - .git/ (existence check only)
  - .agents/runtime/state/runner.lock
  - .agents/runtime/state/automation.log (last 24h)
  - .agents/runtime/state/tasks-state.json
  - .agents/runtime/state/agent-metrics.json
  - .agents/*/agent.json
  - .agents/vision/state/processed-images.json
  - .system/state/inbox-queue.json
outputs:
  - .agents/runtime/state/ (stale lock removed)
  - .agents/*/state/ (missing dirs created)
  - .agents/vision/state/processed-images.json (invalid refs pruned/flagged)
  - .agents/review/state/reports/repair-YYYY-MM-DD.json
  - .agents/repair/state/logs/repair_agent_YYYY-MM-DD.log
dependencies: []
dispatch_config: agent.json
owned_tools:
  - tools/repair_agent.py
responsibilities:
  - GitUpdate: git fetch + git pull --ff-only if project root is a git repository; non-fatal on failure
  - ParseErrorPatterns: scan automation.log (last 24h) for stale-lock / missing-directory / missing-image-ref patterns
  - RemoveStaleLock: delete runner.lock if older than 1800 seconds (30 min)
  - CreateMissingDirs: ensure all directories in shared.defaults.REQUIRED_DIRS exist
  - ValidateImageRefs: verify processed-images.json entries by SHA256 identity; prune missing files, flag hash mismatches
  - DetectOverdueAgents: flag any agent not run within 2 × intervalSeconds
  - WriteRepairReport: emit repair-YYYY-MM-DD.json to .agents/review/state/reports/
restrictions:
  - Must not call any LLM
  - Must not modify 02-Library/
  - Must not delete source files from 00-Inbox/
  - Must not modify vault content files (.md, images)
state_files:
  - state/logs/12-repair-agent_YYYY-MM-DD.log
commit_scope:
  # none — repair-agent edits code/state only; must not auto-commit (no knowledge-base output)
---
