# Agent Spec - Review

**Trigger:** every 15 minutes  
**Input:** `01-Processing/*.md`, `02-Library/*.md`, `system/state/inbox-queue.json`, `agents/runtime/state/logs/automation.log` (last 24h)  
**Output:** `agents/review/state/reports/report-YYYY-MM-DD.json`  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: review.tools.daily_report`

---

## Report Contents

- **Pending review list:** drafts with `reviewed: false`
- **Orphan detection:** drafts with empty `relationships`
- **Quality suggestions:** completeness score per draft
- **Log summary:** errors/warnings per agent (last 24h)
- **Queue depth:** total / pending / done

---

## Task Variant: Short-File Flagging (`review-agent-short-files`)

**Trigger:** hourly  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: review.tools.flag_short_files`  
Scans `01-Processing/*.md` for files with <10 body lines.  
Sets `needs_reprocessing: true` in frontmatter.

---

## Constraints

- Cannot approve content
- Cannot modify `02-Library/`
