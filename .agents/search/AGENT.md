---
name: search
purpose: >
  Provides semantic search across the vault, indexing 02-Library/ and 01-Processing/
  entities into a queryable vector store. Answers DM queries with wikilink citations.
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
  - Read-only on all vault directories
state_files: []
---
