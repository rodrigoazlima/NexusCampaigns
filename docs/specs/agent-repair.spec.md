# Agent Spec — Repair

**Trigger:** every 15 minutes  
**Input:** `.agents/runtime/state/logs/automation.log` (last 24h), `.agents/*/agent.json`, `.agents/runtime/state/tasks-state.json`, `.agents/runtime/state/runner.lock`, `.agents/runtime/state/agent-metrics.json`  
**Output:** `.agents/review/state/reports/repair-YYYY-MM-DD.json`  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: repair.tools.repair_agent`

---

## Fixable Patterns

| Pattern (regex, case-insensitive) | Fix label |
|-----------------------------------|-----------|
| `stale\s+lock` / `lock\s+file.*older` / `runner\.lock` | `stale-lock` |
| `directory.*not\s+found` / `cannot\s+find\s+path` | `missing-directory` |
| `missing_image_ref` | `missing-image-ref` |

## Repair Actions

| Fix label | Action |
|-----------|--------|
| `stale-lock` | Delete `runner.lock` if > 30 min old |
| `missing-directory` | Create missing `.system/` subdirectories |
| `missing-image-ref` | Validate image refs in `processed-images.json` using SHA256 identity (not filename) |

---

## Overdue Detection

Agent not run within `2 × intervalSeconds` → flagged in report.

---

## Constraints

- Cannot approve content
- Cannot modify `02-Library/`
- Cannot restart OS services
