# Agent Spec — Cleanup

**Trigger:** daily  
**Input:** `agents/runtime/state/logs/`, `agents/review/state/reports/`, `agents/runtime/state/agent-metrics.json`  
**Config:** `cleanupDays` from orchestrator `agent.json` (default: 90)  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: cleanup.tools.cleanup_agent`

---

## Responsibilities

- Purge log files older than `cleanupDays`
- Purge report files older than `cleanupDays`
- Trim `agent-metrics.json` run history to last 100 entries per agent
