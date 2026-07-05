---
name: review
purpose: >
  Aggregates automation execution logs and scans vault health every 15 minutes.
  Produces a JSON report with run counts, errors, and warnings per agent, plus
  a vault health section listing pending-review drafts, orphan nodes, and quality
  scores. Rebuilds the reports-data.js dashboard data file after every report.
inputs:
  - agents/runtime/state/logs/automation.log
  - vault://01-Processing/**/*.md
  - agents/*/agent.json  (task discovery for interval data)
outputs:
  - state/reports/report-{YYYY-MM-DD}.json
  - state/reports/reports-data.js
  - vault://01-Processing/**/*.md (suggestedQuality field injected if quality: 0)
  - state/logs/08-daily-report_YYYY-MM-DD.log
dependencies: []
dispatch_config: agent.json
owned_tools:
  - tools/daily_report.py
  - tools/flag_short_files.py
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
  - Embed TASK_CONFIG and TASK_INTERVALS from agent.json discovery into reports-data.js
restrictions:
  - Must not approve content
  - Must not modify 02-Library/
  - May only write suggestedQuality to 01-Processing/ files (no other field modification)
state_files:
  - state/reports/
  - state/logs/08-daily-report_YYYY-MM-DD.log
commit_scope:
  - .knowledge-base/01-Processing
vault_context:
  quality_scale:
    1-3: reject
    4-6: needs review
    7-8: good
    9-10: library candidate — only quality >= 7 may enter 02-Library/
  human_only_fields: [status: approved, reviewed: true]
  orphan_rule: every 02-Library/ entity must have >=1 [[wikilink]]; flag zero-link entities
  canon_rule: status: approved is canon — never overwrite or modify without reviewed re-set by human
---
