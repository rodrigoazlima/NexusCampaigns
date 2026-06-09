---
name: relationship
purpose: >
  Generates and maintains cross-link indexes in 04-Relationships/ by scanning
  02-Library/ entities and computing faction networks, NPC location graphs,
  and timeline sequences.
inputs: []
outputs: []
dependencies:
  - canon
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: TBD
  fallbacks: []
owned_tools: []
responsibilities: []
restrictions:
  - Must not modify 02-Library/
  - Output goes to 04-Relationships/ only
state_files: []
---
