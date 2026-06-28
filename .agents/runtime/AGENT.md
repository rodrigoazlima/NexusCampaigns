---
name: runtime
purpose: >
  The Python scheduler and dispatch runtime for the vault agent pipeline.
  This is the ONLY component with static Python code — it is NOT an AI agent.
  It discovers agents from agent.json files, checks intervals, dispatches Claude
  agents via the Anthropic API, commits vault changes to git, and maintains
  execution state. Single entry point for Windows Task Scheduler.
inputs:
  - .agents/*/agent.json  (task discovery — no tasks.json needed)
  - state/tasks-state.json
outputs:
  - state/tasks-state.json
  - state/logs/automation.log
  - git commits after each agent run
dependencies: []
dispatch_config: null  # runtime itself is not dispatched — it IS the dispatcher
owned_tools:
  - tools/runner.py
  - tools/daemon.ps1
  - tools/install-service.ps1
responsibilities:
  - Discover agents by scanning .agents/*/agent.json for task definitions
  - Check elapsed vs intervalSeconds per task; dispatch due agents sequentially
  - Resolve agent folder from task.id; load agent.json; select runner via dispatch.type
  - Delegate execution to shared runner (claude-api, openai-api, gemini-api, etc.)
  - Write per-task daily log + master automation.log
  - git add scoped to commit_scope + commit after each successful agent run
  - Maintain runner.lock (30-min stale timeout)
restrictions:
  - Must not run agents in parallel
  - Must not modify vault content directly
  - Must not skip git commit step when vault has changes
  - Does not contain AI/LLM logic — only scheduling, dispatch, and state management
state_files:
  - state/tasks-state.json  (lastRun timestamps per task)
  - state/logs/automation.log
  - state/logs/runner_YYYY-MM-DD.log
commit_scope:
  # none — orchestrator state is local runtime bookkeeping; must not auto-commit
---
