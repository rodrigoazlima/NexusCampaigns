---
name: review
purpose: >
  Aggregates automation execution logs and scans vault health every 15 minutes.
  Produces a JSON report with run counts, errors, and warnings per agent, plus
  a vault health section listing pending-review drafts, orphan nodes, and quality
  scores. Rebuilds the reports-data.js dashboard data file after every report.
inputs:
  - .agents/orchestrator/state/logs/automation.log
  - vault://01-Processing/**/*.md
  - .agents/orchestrator/state/tasks.json
outputs:
  - state/reports/report-{YYYY-MM-DD}.json
  - state/reports/reports-data.js
  - vault://01-Processing/**/*.md (suggestedQuality field injected if quality: 0)
  - state/logs/08-daily-report_YYYY-MM-DD.log
dependencies: []
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: none
  fallbacks: []
owned_tools:
  - tools/08-daily-report.ps1
responsibilities:
  - Parse automation.log for all lines in last 24h matching [timestamp][taskId] format
  - Count START/DONE markers per task to compute runs and completedRuns
  - Classify non-structural lines as error/warning/info by keyword match
  - Build per-task summary with firstRun/lastRun timestamps
  - Scan 01-Processing/*.md for vault health metrics
  - Identify pending review: files with reviewed: false or status: draft
  - Identify orphans: files with no [[wikilink]] anywhere in content
  - Compute quality score 0-10: +2 each for description section, relationships with links, 3+ tags, type field, source field
  - Inject suggestedQuality into frontmatter of quality:0 files that lack it
  - Write report JSON to state/reports/report-{date}.json
  - Rebuild state/reports/reports-data.js embedding all historical report JSONs
  - Embed TASK_CONFIG and TASK_INTERVALS from tasks.json into reports-data.js
restrictions:
  - Must not approve content
  - Must not modify 02-Library/
  - May only write suggestedQuality to 01-Processing/ files (no other field modification)
state_files:
  - state/reports/
  - state/logs/08-daily-report_YYYY-MM-DD.log
---
