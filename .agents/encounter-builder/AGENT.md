---
name: encounter-builder
purpose: >
  Generates tactical Pathfinder 2e encounter stat blocks and battlefield descriptions
  from canon creatures, locations, and scenario context. Writes encounter files to
  03-Campaigns/{arc}/encounters/.
inputs: []
outputs: []
dependencies:
  - lore
  - vision
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
  - Output goes to 03-Campaigns/ only
  - Creature stats must reference canon entries in 02-Library/
state_files: []
---
