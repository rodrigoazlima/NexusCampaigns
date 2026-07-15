# Agent Spec — Classification

**Trigger:** hourly  
**Input:** notes in `00-Inbox/` and `01-Processing/` with ≤5 tags, missing `type:`, or unreviewed vision `candidate_tags`; `system/state/inbox-queue.json`; `state/tag-library.json`  
**Output:** enriched frontmatter in-place  
**Dependency:** LM Studio at `http://localhost:1234` — text via the `classification_text_llm` registry alias, vision via `vision_llm`  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: classification.tools.enrich_tags`

---

## Model Selection (agent.json)

Both of this agent's LLM calls are model-selectable per install via
`agent.json` (`tasks.classification-agent.llm`), resolved by
`load_llm_endpoint(..., model_key=...)` on top of the registry alias:

```json
"llm": {
  "text_model": "qwen/qwen3.5-9b",
  "vision_model": "qwen3-vl-4b-instruct"
}
```

- `text_model` overrides `classification_text_llm`'s model (tag/type inference, no image).
- `vision_model` overrides `vision_llm`'s model for this agent's own
  image-grounded refinement call — independent of what the vision agent runs.

Any model id served by the endpoint's `/v1/models` is valid; the defaults
above are verified locally on LM Studio. Fresh clones get this block
scaffolded by the maintenance worker (`_AGENT_JSON_SPECS`).

---

## Responsibilities

1. Assign free-form DM-domain tags to notes with sparse tagging, or notes whose
   source image carries unreviewed vision `candidate_tags` — no fixed vocabulary.
2. Infer `type:` field if missing.
3. When unreviewed `candidate_tags` exist and the source image resolves on
   disk, run `refine_tags_with_library()` (public function from
   `vision.tools.classify_images`, using this agent's own configured vision
   model) as an image-grounded second opinion — merged add-only on top of the
   text pass; its failures never fail the file.
4. Flag potential duplicates against `02-Library/` by slug similarity.

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
