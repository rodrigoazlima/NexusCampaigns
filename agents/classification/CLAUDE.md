# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Second-stage agent of the vault pipeline (see repo-root `CLAUDE.md` for the full architecture). Enriches sparse `.md` notes in `00-Inbox/` and `01-Processing/` with DM-domain tags and inferred entity `type`, and flags likely duplicates against `02-Library/`. Dispatched via `lm-studio` (`agent.json`), but the actual tag/type inference calls a separate **LocalRouter** endpoint at `localhost:8080` (`LLMClient` in `tools/enrich_tags.py`) — not the LM Studio model driving the tool-call loop.

## Commands

```powershell
# Run standalone (bypasses runner scheduling)
python tools/enrich_tags.py

# Run via the shared scheduler (from repo root)
python agents/runtime/tools/runner.py --task classification-agent --force

# Relevant tests (repo root)
pytest agents/tests/test_classification.py
```

## Layout

- `tools/enrich_tags.py` — all logic; three actions exposed as tools (`enrich_tags`, `infer_type`, `flag_duplicates`) plus `call_tool()` for agentic dispatch.
- `agent.json` — task config (hourly, `lm-studio` dispatch, `tools_module: classification.tools.enrich_tags`).
- `AGENT.md` — contract: inputs/outputs, `commit_scope`, allowed tags/types lists, restrictions (read before changing behavior).
- `prompts/system.md` — step order for the dispatched model (`enrich_tags` → `infer_type` → `flag_duplicates` → `write_log`).
- `prompts/enrich-tags.txt` — the actual tagging/typing prompt sent to LocalRouter, including the dashboard-tab-to-entity-type mapping; keep in sync with `_ALLOWED_TAGS`/`_ALLOWED_TYPES` in code if either changes.
- `.agents`, `.knowledge-base`, `.system` — symlinks into `agents/shared/`, the vault, and `system/state/` respectively (same pattern as sibling agents).

## Actions (in `tools/enrich_tags.py`)

1. **`enrich_tags`** (`_run_enrich_tags`) — main pass, batch size 20. For each candidate file needing tags (≤2 existing) or type (missing, or a vision-agent placeholder default not yet human-reviewed), sends one LLM call combining both, validates output against `_ALLOWED_TAGS`/`_ALLOWED_TYPES`, merges tags (never removes), and marks the file's slot done in `system/state/inbox-queue.json`.
2. **`infer_type`** (`_run_infer_type`) — narrower follow-up pass, type-only, `max_tokens=10`, no batch cap; for notes `enrich_tags` didn't fully resolve.
3. **`flag_duplicates`** (`_run_flag_duplicates`) — exact slug match against `02-Library/` takes priority; otherwise difflib similarity ≥ `_SIMILARITY_THRESHOLD` (0.85) sets `duplicate_of: similar_to:<slug>(<score>)`.

## Conventions specific to this agent

- `_VISION_DEFAULTS` (`npc`, `location`) are placeholder types the vision agent assigns to portraits/battlemaps — this agent treats them as "still needs refinement" until a human sets `reviewed: true`, at which point they're frozen.
- `_IMAGE_TYPE_HINTS` maps vision image-classification tags (`portrait`, `body`, `token`, `battlemap`, `scene`) to plausible entity types, injected into the prompt as a hint line — keep in sync with the vision agent's tag vocabulary.
- `_candidate_files()` excludes any path containing `agents` in its parts, in addition to `.git`, to avoid scanning generated agent-owned markdown.
- Queue coordination (`_load_queue`/`_is_queue_done`/`_mark_queue_done`) reads/writes the *shared* `system/state/inbox-queue.json`, not this agent's own `state/`; marking done also traces `.md` → source image via the `source` frontmatter field so both queue entries advance together.
- `_write_with_retry` calls `_assert_not_library()` before every write — hard guard against ever touching `02-Library/`, independent of the `AGENT.md` restriction.
- All three tools are additive/idempotent — re-running is safe; already-tagged/typed/flagged files are skipped via the `needs_tags`/`needs_type`/exact-slug checks.

## Vault-wide rules (from repo-root `AGENTS.md` / `CLAUDE.md`)

- Agent priority order for the whole pipeline: reusability > consistency > traceability > human review > knowledge-graph connectivity — `flag_duplicates` directly serves reusability/consistency by catching near-duplicate entities before they reach `02-Library/`.
- Only humans may set `reviewed: true` / `status: approved` — no agent in this repo does.
- Never remove existing tags, only add/merge.
- `02-Library/` is read-only for this agent (slug list for dedup only); canon there may not be overwritten or modified without a human re-setting `reviewed: true`.
- Entity `type` values are a closed set (`npc`, `character`, `faction`, `location`, `city`, `village`, `dungeon`, `item`, `artifact`, `quest`, `encounter`, `creature`, `monster`, `event`, `religion`, `organization`, `timeline`, `lore`) — do not invent new ones; matches `_ALLOWED_TYPES` in code.
- `AGENTS.md`'s own "Enrich Agent" section describes an **older spec** of this agent (threshold "≤5 tags", no type-inference or dedup responsibilities) — current code (`tools/enrich_tags.py`) uses "≤2 tags" and additionally does type inference (`infer_type`) and duplicate flagging (`flag_duplicates`); trust the code and this file over that section.
- Naming/linking rules (slug format, no orphan entities) apply to the notes this agent touches but are enforced elsewhere (ingestion for naming, wiki agent for linking) — this agent only adds `tags`/`type`/`duplicate_of`, it does not rename files or add relationships.
