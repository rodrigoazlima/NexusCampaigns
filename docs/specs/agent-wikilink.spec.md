# Agent Spec — Wikilink (`14-wikilink-library.py`)

**Trigger:** hourly  
**Input:** `02-Library/**/*.md`  
**Output:** `[[wikilink]]` insertions in `## Related` section of each note

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
