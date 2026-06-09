---
name: curator
purpose: >
  Assists human curation by scoring 01-Processing/ drafts for Library promotion
  readiness, suggesting which drafts are ready (quality >= 7, reviewed, linked),
  and preparing promotion summaries.
inputs: []
outputs: []
dependencies:
  - review
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
  - May not set reviewed: true
  - May not promote content to 02-Library/ automatically
state_files: []
---
