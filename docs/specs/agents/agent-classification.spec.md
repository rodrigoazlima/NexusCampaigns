# Agent Spec — Classification

**Trigger:** hourly  
**Input:** notes in `00-Inbox/` and `01-Processing/` with ≤5 tags, missing `type:`, or unreviewed vision `candidate_tags`; `system/state/inbox-queue.json`; `state/tag-library.json`  
**Output:** enriched frontmatter in-place  
**Dependency:** LocalRouter at `http://localhost:8080`  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: classification.tools.enrich_tags`

---

## Responsibilities

1. Assign free-form DM-domain tags to notes with sparse tagging, or notes whose
   source image carries unreviewed vision `candidate_tags` — no fixed vocabulary.
2. Infer `type:` field if missing.
3. Flag potential duplicates against `02-Library/` by slug similarity.

---

## Tag Library

Tags are not validated against a fixed list. Each tag the LLM returns is passed
through `_canonicalize_tag()` against `state/tag-library.json`: an exact match
reuses the existing canonical entry; a fuzzy match — shared-prefix ratio
(`_tag_prefix_ratio`) ≥ `_TAG_FOLD_THRESHOLD` (0.65), a different heuristic
from the character-overlap `_slug_similarity` used for duplicate-slug
detection — folds the new spelling into whichever tag was registered first,
recording it as an alias (e.g. "elven" folds into "elf" if "elf" already
exists); no match registers a brand-new canonical tag. The prompt shows the model both the note's harvested
`candidate_tags` (from vision) and a sample of `known_tags` (most-used library
entries) so it prefers reusing existing tags over inventing synonyms.

---

## Constraints

- Cannot approve content
- Cannot create canon
- Cannot modify `02-Library/`
