---
name: orchestrator
purpose: >
  Dispatches all vault automation agents on schedule. Reads tasks.json to determine
  which agents are due, runs them synchronously, commits vault changes to git, and
  maintains execution state. Single entry point for Windows Task Scheduler.
inputs:
  - state/tasks.json
  - state/tasks-state.json
  - state/settings.json
outputs:
  - state/tasks-state.json
  - state/logs/automation.log
  - git commits after each agent run
dependencies: []
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: none
  fallbacks: []
owned_tools:
  - tools/runner.ps1
  - tools/register-tasks.ps1
  - tools/deregister-tasks.ps1
responsibilities:
  - Check elapsed vs intervalSeconds per task; run due tasks sequentially
  - Write per-task daily log + master automation.log
  - git add -A + commit + push after each agent run with vault changes
  - Maintain runner.lock (30-min stale timeout)
restrictions:
  - Must not run agents in parallel
  - Must not modify vault content directly
  - Must not skip git commit step when vault has changes
state_files:
  - state/tasks.json
  - state/tasks-state.json
  - state/settings.json
  - state/logs/automation.log
  - state/logs/runner_YYYY-MM-DD.log
---
