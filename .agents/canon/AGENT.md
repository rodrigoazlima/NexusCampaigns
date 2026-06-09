---
name: canon
purpose: >
  Validates consistency of approved entities in 02-Library/ against each other.
  Detects contradictions, missing relationships, and broken wikilinks. Produces
  a canon integrity report.
inputs: []
outputs: []
dependencies: []
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: TBD
  fallbacks: []
owned_tools: []
responsibilities: []
restrictions:
  - Read-only on 02-Library/
  - Must not modify any approved entity without explicit human action
state_files: []
---
