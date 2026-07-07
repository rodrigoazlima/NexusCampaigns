---
name: cleanup
purpose: >
  Daily housekeeping. Deletes log and report files older than cleanupDays
  (from cleanup/agent.json). Trims agent-metrics.json run history to the last 100
  entries per agent. Keeps disk usage bounded without human intervention.
inputs:
  - agents/runtime/state/logs/           (log files)
  - agents/review/state/reports/              (review report files)
  - agents/repair/state/reports/              (repair report files)
  - agents/canon/state/reports/               (canon report files)
  - agents/deduplication/state/reports/       (dedup report files)
  - agents/cleanup/state/reports/             (cleanup report files)
  - agents/cleanup/agent.json             (cleanupDays setting)
outputs:
  - (files deleted in-place across log/report directories)
  - state/reports/cleanup-{YYYY-MM-DD}.json
  - state/logs/cleanup_YYYY-MM-DD.log
dependencies: []
dispatch_config: agent.json
owned_tools:
  - system/src/nexus/tasks/cleanup_agent.py
responsibilities:
  - Read cleanupDays from agent.json top-level field (default 90 if absent)
  - Walk all log directories; delete .log files with mtime > cleanupDays
  - Walk all report directories; delete .json report files with mtime > cleanupDays
  - Load agent-metrics.json; trim each agent's runs list to last 100 entries; write back atomically
  - Write CleanupReport JSON to state/reports/cleanup-{date}.json
  - Emit START/DONE log markers via shared Logger
restrictions:
  - Must not delete state files (inbox-queue.json, processed-*.json, etc.)
  - Must not delete tasks-state.json or any agent.json
  - Must not touch 00-Inbox/, 01-Processing/, 02-Library/
  - Must not run more than once per calendar day (enforced by runtime interval)
state_files:
  - state/reports/
  - state/logs/cleanup_YYYY-MM-DD.log
commit_scope:
  # none — agent produces no knowledge-base content; must not auto-commit
---
