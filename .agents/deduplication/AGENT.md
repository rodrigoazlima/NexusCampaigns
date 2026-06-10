---
name: deduplication
purpose: >
  Deep deduplication across 00-Inbox/, 01-Processing/, and 02-Library/ using
  slug matching, shared-tag overlap, and body content similarity. Produces
  DedupReport listing merge candidates above threshold. Flags files for human
  review — never deletes or merges automatically.
inputs:
  - vault://00-Inbox/**/*.md
  - vault://01-Processing/**/*.md
  - vault://02-Library/**/*.md
  - .agents/deduplication/state/dedup-report-latest.json
outputs:
  - .agents/deduplication/state/dedup-report-latest.json
  - .agents/deduplication/state/reports/dedup-{YYYY-MM-DD}.json
  - state/logs/deduplication_YYYY-MM-DD.log
dependencies:
  - classification
dispatch_config: agent.json
owned_tools:
  - tools/deduplication_agent.py
responsibilities:
  - Collect all .md paths from the three vault directories
  - Build slug pairs: flag exact slug matches across directories as DedupCandidate (slug reason, score 1.0)
  - For non-exact pairs: compute tag overlap score = shared_tags / max(len(a_tags), len(b_tags)); flag pairs >= 0.6 (tags reason)
  - For slug or tag matches: compute body similarity (Jaccard on word sets); upgrade to content reason if >= 0.5
  - Write DedupReport to dedup-report-latest.json and dated archive
  - Emit START/DONE log markers via shared Logger
restrictions:
  - Must not delete files
  - Must not modify 02-Library/ without human approval
  - Must not call any LLM
  - Read-only on all vault directories
state_files:
  - state/dedup-report-latest.json
  - state/reports/
  - state/logs/deduplication_YYYY-MM-DD.log
commit_scope:
  - .agents/deduplication/state
---
