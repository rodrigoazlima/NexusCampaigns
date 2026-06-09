# Agent Spec — Review (`08-daily-report.ps1`)

**Trigger:** every 15 minutes  
**Input:** `01-Processing/*.md`, `02-Library/*.md`, `inbox-queue.json`, `.system/logs/automation.log` (last 24h)  
**Output:** `.system/reports/report-YYYY-MM-DD.json`

---

## Report Contents

- **Pending review list:** drafts with `reviewed: false`
- **Orphan detection:** drafts with empty `relationships`
- **Quality suggestions:** completeness score per draft
- **Log summary:** errors/warnings per agent (last 24h)
- **Queue depth:** total / pending / done

---

## Sub-agent: Short-File Flagging (`15-flag-short-files.py`)

**Trigger:** hourly  
Scans `01-Processing/*.md` for files with <10 body lines.  
Sets `needs_reprocessing: true` in frontmatter.

---

## Constraints

- Cannot approve content
- Cannot modify `02-Library/`
