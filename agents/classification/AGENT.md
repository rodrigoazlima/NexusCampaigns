---
name: classification
purpose: >
  Enriches .md files in 00-Inbox/ and 01-Processing/ with free-form DM-domain tags
  (canonicalized against a growing tag library, not a fixed vocabulary) and entity
  type inference via a configurable text LLM, plus an image-grounded second opinion
  via a configurable vision LLM (refine_tags_with_library). Detects potential
  duplicates against 02-Library/ slugs. Modifies frontmatter in-place. Processes
  files with 5 or fewer existing tags, missing type field, or unreviewed vision
  candidate_tags.
inputs:
  - vault://00-Inbox/**/*.md
  - vault://01-Processing/**/*.md
  - vault://02-Library/**/*.md (read-only: slug list for dedup check)
  - state/bad-docs.txt
  - LLM (text): classification_text_llm registry alias, LM Studio by default —
    model selectable via agent.json tasks.classification-agent.llm.text_model
  - LLM (vision): vision_llm registry alias (same LM Studio instance vision
    agent uses) — model selectable via .llm.vision_model
outputs:
  - vault://00-Inbox/**/*.md (frontmatter updated in-place)
  - vault://01-Processing/**/*.md (frontmatter updated in-place)
  - state/bad-docs.txt (failed files appended)
  - state/logs/04-enrich-tags_YYYY-MM-DD.log
dependencies:
  - ingestion
  - wiki
dispatch_config: agent.json
owned_tools:
  - tools/04-enrich-tags.ps1
responsibilities:
  - Pre-flight check the configured text LLM before processing
  - Load bad-docs.txt skip list on startup
  - Load 02-Library/ slug list once per run for dedup comparison
  - For each .md in 00-Inbox/ and 01-Processing/: parse YAML frontmatter
  - Skip files in bad-docs.txt
  - If tags count <= 5, type field missing, or source image has unreviewed
    candidate_tags: call tag LLM with title + 500-char body snippet + candidate
    tags (from vision) + known tags (top of the tag library)
  - Canonicalize each returned tag against state/tag-library.json (shared-prefix
    ratio ≥0.65 folds inflections/variants into the first-seen spelling; no
    match registers a new canonical tag) — no fixed tag vocabulary
  - Validate type against 18-type allowed list
  - When candidate_tags are unreviewed and the source image still resolves on
    disk: call refine_tags_with_library() (imported from
    vision.tools.classify_images, using the configured vision LLM) for an
    image-grounded second opinion, merging its final tags (add-only) and
    entity type on top of the text-only pass
  - Compare slug against library slugs (exact lowercase match) → inject duplicate_of field
  - Merge new tags with existing (deduplicated); rebuild frontmatter
  - Write updated file with 5-retry loop (handles lock contention)
  - Add to bad-docs.txt on parse failure or persistent LLM failure
  - 300ms sleep between file writes
restrictions:
  - Must not approve content
  - Must not create canon entries
  - Must not modify 02-Library/ files
  - Must not remove existing tags (only add/merge)
  - Tag LLM max 80 tokens; type LLM max 10 tokens; vision refinement max 1024 tokens
  - Vision refinement failures (offline, parse error) never fail the file — falls back to the text-only result
state_files:
  - state/bad-docs.txt
  - state/tag-library.json
commit_scope:
  - .knowledge-base/00-Inbox
  - .knowledge-base/01-Processing
---

## Tag Library

Tags are no longer a fixed list — the LLM proposes freely and `_canonicalize_tag()`
folds near-duplicate spellings into whichever one was registered first in
`state/tag-library.json` (e.g. "elven"/"elfo" fold into "elf" if "elf" already
exists there, via a shared-prefix ratio ≥ `_TAG_FOLD_THRESHOLD` (0.65) — a
different, word-scale heuristic from the character-overlap `_slug_similarity`
used for duplicate-slug detection). New tags register themselves as new
canonical entries.

`refine_tags_with_library()` (public function, `agents/vision/tools/classify_images.py`)
gives this agent its own image-grounded second opinion using the same library,
via a separately-configurable vision LLM — see `agent.json`'s `llm.vision_model`.

## Valid Types (18)
npc · character · faction · location · city · village · dungeon · item · artifact · quest · encounter · creature · monster · event · religion · organization · timeline · lore
