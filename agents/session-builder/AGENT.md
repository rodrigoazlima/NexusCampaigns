---
name: session-builder
purpose: >
  Generates individual session plans, scene-by-scene, from adventure modules and
  recent session notes. Writes session prep documents to 03-Campaigns/{arc}/sessions/.
inputs: []
outputs: []
dependencies:
  - adventure-builder
dispatch_config: agent.json
owned_tools: []
responsibilities: []
restrictions:
  - Output goes to 03-Campaigns/ only
state_files: []
---
