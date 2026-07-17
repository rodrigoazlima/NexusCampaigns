# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Second-stage agent of the vault pipeline (see repo-root `CLAUDE.md` for the full architecture). Enriches sparse `.md` notes in `00-Inbox/` and `01-Processing/` with DM-domain tags and inferred entity `type`, and flags likely duplicates against `02-Library/`. Two LLM calls of its own, both LM Studio (`localhost:1234`), both model-selectable via `agent.json` `tasks.classification-agent.llm`: a text-only call (`classification_text_llm` registry alias, override with `llm.text_model`) for tag/type inference, and a vision call (`vision_llm` alias, override with `llm.vision_model`) powering `refine_tags_with_library`'s image-grounded second opinion. Neither is the model driving the agent's own dispatch loop - that's `agent.json`'s `dispatch` block, unrelated.

## Commands

```powershell
# Run standalone (bypasses runner scheduling)
python tools/enrich_tags.py

# Run via the shared scheduler (from repo root)
python -m nexus.runner --task classification-agent --force

# Relevant tests (repo root)
pytest agents/tests/test_classification.py
```

## Layout

- `tools/enrich_tags.py` - all logic; three actions exposed as tools (`enrich_tags`, `infer_type`, `flag_duplicates`) plus `call_tool()` for agentic dispatch.
- `agent.json` - task config (hourly, `lm-studio` dispatch, `tools_module: classification.tools.enrich_tags`).
- `AGENT.md` - contract: inputs/outputs, `commit_scope`, allowed types list + tag-library description, restrictions (read before changing behavior).
- `prompts/system.md` - step order for the dispatched model (`enrich_tags` → `infer_type` → `flag_duplicates` → `write_log`).
- `prompts/enrich-tags.txt` - the actual tagging/typing prompt sent to the configured text LLM, including the dashboard-tab-to-entity-type mapping and the `{candidate_tags}`/`{known_tags}` hint lines; keep the entity-type list in sync with `_ALLOWED_TYPES` in code if it changes (tags themselves are no longer a fixed list).
- `.agents`, `.knowledge-base`, `.system` - symlinks into `agents/shared/`, the vault, and `system/state/` respectively (same pattern as sibling agents).

## Actions (in `tools/enrich_tags.py`)

1. **`enrich_tags`** (`_run_enrich_tags`) - main pass, batch size 20. For each candidate file needing tags (≤2 existing), type (missing, or a vision-agent placeholder default not yet human-reviewed), or carrying unreviewed vision `candidate_tags`, sends one LLM call combining all three, canonicalizes returned tags against `state/tag-library.json` (`_canonicalize_tag`) and validates type against `_ALLOWED_TYPES`, merges tags (never removes), and marks the file's slot done in `system/state/inbox-queue.json`.
2. **`infer_type`** (`_run_infer_type`) - narrower follow-up pass, type-only, `max_tokens=10`, no batch cap; for notes `enrich_tags` didn't fully resolve.
3. **`flag_duplicates`** (`_run_flag_duplicates`) - exact slug match against `02-Library/` takes priority; otherwise difflib similarity ≥ `_SIMILARITY_THRESHOLD` (0.85) sets `duplicate_of: similar_to:<slug>(<score>)`.

## Conventions specific to this agent

- `_VISION_DEFAULTS` (`npc`, `location`) are placeholder types the vision agent assigns to portraits/battlemaps - this agent treats them as "still needs refinement" until a human sets `reviewed: true`, at which point they're frozen.
- `_IMAGE_TYPE_HINTS` maps vision image-classification tags (`portrait`, `body`, `token`, `battlemap`, `scene`) to plausible entity types, injected into the prompt as a hint line - keep in sync with the vision agent's tag vocabulary.
- `_source_candidate_tags()` traces a note's `source` frontmatter to its queue entry/entries and reads the `candidate_tags` the vision agent left there (`classify_images._mark_vision_done`) - same indirect-lookup pattern `_mark_queue_done` already uses. A non-empty result is its own trigger (`needs_candidate_review`) independent of `needs_tags`/`needs_type`.
- `_canonicalize_tag()` + `state/tag-library.json` replace the old fixed `_ALLOWED_TAGS` list: exact key reuse, else fuzzy-match via `_tag_prefix_ratio` (shared-prefix length / shorter tag's length, ≥ `_TAG_FOLD_THRESHOLD` 0.65 - deliberately not `_slug_similarity`/`_SIMILARITY_THRESHOLD`, which is character-overlap based and gets short single words backwards: it scores "elf"/"self" higher than "elf"/"elven") folds a new spelling into the first-seen canonical tag and records it as an alias; no match registers a brand-new tag. `known_tags` (top of the library by `count`) is injected into the prompt so the model prefers reusing existing tags before this fold even runs.
- `_candidate_files()` excludes any path containing `agents` in its parts, in addition to `.git`, to avoid scanning generated agent-owned markdown.
- Queue coordination (`_load_queue`/`_is_queue_done`/`_mark_queue_done`) reads/writes the *shared* `system/state/inbox-queue.json`, not this agent's own `state/`; marking done also traces `.md` → source image via the `source` frontmatter field so both queue entries advance together.
- `_write_with_retry` calls `_assert_not_library()` before every write - hard guard against ever touching `02-Library/`, independent of the `AGENT.md` restriction.
- All three tools are additive/idempotent - re-running is safe; already-tagged/typed/flagged/reviewed-candidate files are skipped via the `needs_tags`/`needs_type`/`needs_candidate_review`/exact-slug checks.

## Vault-wide rules (from repo-root `AGENTS.md` / `CLAUDE.md`)

- Agent priority order for the whole pipeline: reusability > consistency > traceability > human review > knowledge-graph connectivity - `flag_duplicates` directly serves reusability/consistency by catching near-duplicate entities before they reach `02-Library/`.
- Only humans may set `reviewed: true` / `status: approved` - no agent in this repo does.
- Never remove existing tags, only add/merge.
- `02-Library/` is read-only for this agent (slug list for dedup only); canon there may not be overwritten or modified without a human re-setting `reviewed: true`.
- Entity `type` values are a closed set (`npc`, `character`, `faction`, `location`, `city`, `village`, `dungeon`, `item`, `artifact`, `quest`, `encounter`, `creature`, `monster`, `event`, `religion`, `organization`, `timeline`, `lore`) - do not invent new ones; matches `_ALLOWED_TYPES` in code.
- `AGENTS.md`'s own "Enrich Agent" section describes an **older spec** of this agent (threshold "≤5 tags", no type-inference or dedup responsibilities) - current code (`tools/enrich_tags.py`) uses "≤2 tags" and additionally does type inference (`infer_type`) and duplicate flagging (`flag_duplicates`); trust the code and this file over that section.
- Naming/linking rules (slug format, no orphan entities) apply to the notes this agent touches but are enforced elsewhere (ingestion for naming, wiki agent for linking) - this agent only adds `tags`/`type`/`duplicate_of`, it does not rename files or add relationships.
- Tags themselves are **not** a closed set - do not reintroduce a fixed allowlist. Consistency comes from `_canonicalize_tag()` folding synonyms into the tag library, not from rejecting unlisted tags.
