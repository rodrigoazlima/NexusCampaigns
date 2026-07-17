# Agent Spec - Wikilink

**Trigger:** hourly  
**Input:** `02-Library/**/*.md`, `agents/wikilink/state/wikilink-state.json`  
**Output:** `[[wikilink]]` insertions in `## Related` section of each note  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: wikilink.tools.wikilink_library`

---

## Responsibilities

Scan all `02-Library/` notes and insert cross-links into the `## Related` section based on entity similarity scoring.

---

## Scoring

Note-pairs scored by:
- Shared tags
- Slug mentions
- Body keyword overlap

Configurable: `--min-score` and `--max-links`.

---

## Constraints

- Cannot modify frontmatter
- Cannot create new files
