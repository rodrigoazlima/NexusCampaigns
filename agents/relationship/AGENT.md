---
name: relationship
purpose: >
  Generates and maintains cross-link indexes in 04-Relationships/ by scanning
  02-Library/ entities and computing faction networks, NPC location graphs,
  and timeline sequences. Produces a relationship-graph.json state file and
  writes human-readable index pages per relationship type.
inputs:
  - vault://02-Library/**/*.md
  - agents/relationship/state/relationship-graph.json
outputs:
  - agents/relationship/state/relationship-graph.json
  - vault://04-Relationships/faction-network.md
  - vault://04-Relationships/npc-location-index.md
  - vault://04-Relationships/timeline.md
  - state/logs/relationship_YYYY-MM-DD.log
dependencies:
  - ingestion
  - classification
dispatch_config: agent.json
owned_tools:
  - tools/relationship_agent.py
responsibilities:
  - Load all entities from 02-Library/ via EntityScanner
  - For each entity pair: score by shared tags (weight 0.5 each), slug mentions (+1.0), and explicit [[wikilinks]] (+2.0)
  - Emit RelationshipEdge for pairs with total weight >= 1.0
  - Write RelationshipGraph to relationship-graph.json atomically
  - Generate faction-network.md listing all faction→NPC→location chains
  - Generate npc-location-index.md listing each NPC with their known locations
  - Generate timeline.md listing event entities sorted by created date
  - Batch: process all library entities per run (no partial batching)
restrictions:
  - Must not modify 02-Library/
  - Output goes to 04-Relationships/ only
  - Must not call any LLM
  - Must not add relationships field to entity frontmatter (read-only on 02-Library/)
state_files:
  - state/relationship-graph.json
  - state/logs/relationship_YYYY-MM-DD.log
commit_scope:
  - knowledge-base/04-Relationships
---
