# Agent Spec — Cleanup (`13-cleanup.ps1`)

**Trigger:** daily  
**Input:** `.system/logs/`, `.system/reports/`, `.system/agent-metrics.json`  
**Config:** `cleanupDays` from `tasks.json` (default: 90)

---

## Responsibilities

- Purge log files older than `cleanupDays`
- Purge report files older than `cleanupDays`
- Trim `agent-metrics.json` run history to last 100 entries per agent
