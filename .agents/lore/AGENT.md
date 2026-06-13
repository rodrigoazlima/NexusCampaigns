---
name: lore
purpose: >
  Generates Pathfinder 2e NPC character sheets from classified character images crossed
  with active campaign scenarios. For each unprocessed (image, scenario) pair, calls
  Qwen3-VL with a vision payload, injects canon context from 02-Library/, and writes
  AGENTS.md-compliant NPC drafts to 01-Processing/.
inputs:
  - vault://00-Inbox/images/**/*.{png,jpg,jpeg,webp} (character types only)
  - .agents/vision/state/processed-images.json (read-only)
  - state/processed-npcs.json
  - state/scenarios.json
  - .system/state/inbox-queue.json
  - vault://02-Library/**/*.md (read-only: canon context, up to 50 entities)
  - LLM: http://localhost:1234/v1/chat/completions (Qwen3-VL)
outputs:
  - vault://01-Processing/{image-stem}-{scenario-id}.md (NPC draft)
  - state/processed-npcs.json (updated index)
  - .system/state/inbox-queue.json (agents.lore = done)
  - state/logs/09-generate-npcs_YYYY-MM-DD.log
dependencies:
  - ingestion
  - vision
dispatch_config: agent.json
owned_tools:
  - tools/09-generate-npcs.ps1
  - tools/09-generate-npcs.py
responsibilities:
  - Load active scenarios from state/scenarios.json
  - Load eligible character images from vision state (types: portrait, body, token; status: ok)
  - Scan 02-Library/ for up to 50 entities; extract id + type + tags for canon context
  - Build all unprocessed (image, scenario) pairs using composite key rel_path|scenario_id
  - Resize and base64-encode each image (max 1024px, JPEG 85%)
  - Call Qwen3-VL with NPC prompt injected with scenario name/description and library context
  - Validate LLM JSON: name, ancestry, heritage, class, level (1-20), background, ability mods (-5 to +5), abilities (3×), traits, relationships
  - Always inject scenario wikilink as first relationship entry
  - Write draft to 01-Processing/{image-stem}-{scenario-id}.md
  - Record result in processed-npcs.json (status: ok/error-llm/error-image/error-write)
  - Update inbox-queue.json agents.lore = done
  - Batch: 10 image×scenario pairs per run
restrictions:
  - Must not approve content
  - Must not modify 02-Library/
  - Must not set reviewed: true in any output
  - Must not contradict existing canon entities
  - Level must be 1-20; ability modifiers must be integers between -5 and +5
state_files:
  - state/processed-npcs.json
  - state/scenarios.json
commit_scope:
  - knowledge-base/01-Processing
  - .agents/lore/state
  - .system/state
---
