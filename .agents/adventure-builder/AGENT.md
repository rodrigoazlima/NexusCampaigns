---
name: adventure-builder
purpose: >
  Assembles complete adventure modules from canon entities in 02-Library/ and
  active scenarios in lore agent state. Generates structured adventure documents
  in 03-Campaigns/.
inputs: []
outputs: []
dependencies:
  - lore
  - canon
  - relationship
allowed_clis:
  - claude-code
  - opencode
preferred_models:
  primary: TBD
  fallbacks: []
owned_tools: []
responsibilities: []
restrictions:
  - Output goes to 03-Campaigns/ only
  - Must not contradict canon
  - Never produces canon (consumes only)
state_files: []
---
