---
name: curator
purpose: >
  Assists human curation by scoring 01-Processing/ drafts for Library promotion
  readiness. Computes quality scores via QualityGate, identifies blockers
  (low quality, missing relationships, unreviewed), and writes a CuratorReport
  summarising what is ready vs blocked. Never promotes content - that requires
  explicit human action.
inputs:
  - vault://01-Processing/**/*.md
  - agents/curator/state/curator-report-latest.json
outputs:
  - agents/curator/state/curator-report-latest.json
  - state/logs/curator_YYYY-MM-DD.log
dependencies:
  - review
  - classification
dispatch_config: agent.json
owned_tools:
  - tools/curator_agent.py
responsibilities:
  - Scan all .md files in 01-Processing/ via EntityScanner
  - For each draft: call QualityGate.score() and QualityGate.is_library_ready()
  - Collect blockers: quality < 7, reviewed=false, empty relationships, missing type/source
  - Build CuratorSuggestion per draft with ready flag and blocker list
  - Write CuratorReport to curator-report-latest.json atomically
  - Emit START/DONE log markers via shared Logger
restrictions:
  - May not set reviewed: true (human-only field per AGENTS.md)
  - May not promote content to 02-Library/ automatically
  - May not modify frontmatter fields (read-only on 01-Processing/)
  - Must not call any LLM
state_files:
  - state/curator-report-latest.json
  - state/logs/curator_YYYY-MM-DD.log
commit_scope:
  # none - agent produces no knowledge-base content; must not auto-commit
---
