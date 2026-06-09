---
name: deduplication
purpose: >
  Deep deduplication across 00-Inbox/, 01-Processing/, and 02-Library/ using
  semantic similarity and slug matching. Produces dedup reports and flags
  merge candidates for human review.
inputs: []
outputs: []
dependencies:
  - classification
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: TBD
  fallbacks: []
owned_tools: []
responsibilities: []
restrictions:
  - Must not delete files
  - Must not modify 02-Library/ without human approval
state_files: []
---
