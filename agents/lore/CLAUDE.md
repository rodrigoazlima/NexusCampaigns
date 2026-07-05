# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Run this agent once, bypassing due/precondition checks (from repo root)
python agents/runtime/tools/runner.py --task lore-agent --force

# Run the batch script directly (LM Studio must be running at localhost:1234)
python agents/lore/tools/generate_npcs.py

# Tests (no dedicated lore test file exists yet; runs whole suite from repo root)
pytest
```

`.agents/` and `.system/` in this folder are symlinks (`shared` → `agents/shared`, `vision` → `agents/vision`, `state` → `system/state`) — read/follow through them, don't edit the link targets from here without checking the source folder's own docs.

## Architecture

**Purpose:** generates PF2e NPC character sheets by crossing classified character images (from the vision agent) with active campaign scenarios, via a local vision LLM (LM Studio, `qwen3-vl-4b-instruct` at `http://localhost:1234`). Drafts land in `.knowledge-base/01-Processing/`, never `02-Library/`.

**Pipeline position:** `ingestion` → `vision` (classifies images) → **`lore`** (this agent, generates NPCs) → human review → `02-Library/`. See `docs/specs/agents/agent-lore.spec.md` for the full contract.

**Core logic** lives in `tools/generate_npcs.py`, exposed as both a CLI (`main()`) and an agentic tool module (`TOOLS` list + `call_tool()`, used by the `claude-api`/`lm-studio` dispatch runner):
- `list_pending_pairs` — builds unprocessed `(image, scenario)` pairs via composite key `rel_path|scenario_id`, checked against `state/processed-npcs.json`. Only images with `type ∈ {portrait, body, token}` and `status: ok` in `agents/vision/state/processed-images.json` are eligible.
- `load_canon_context` — scans up to 50 entities in `.knowledge-base/02-Library/` (id, type only) to inject as context and avoid contradicting canon.
- `generate_npc` / `run_batch` — calls the vision LLM per pair (`_NPCGeneratorImpl.generate`), then runs a **reflexion loop**: `QualityGate.score()` the draft, and if < 7, call `generate_with_critique` with a gap-specific critique (from `_build_critique`) up to `_MAX_REVISIONS` (2) rounds, keeping the best-scoring version. Still < 7 after that → draft is written with `needs_human_review: true` + a `## Reviewer Notes` section, never silently dropped.
- `_normalize_stats` — LLMs sometimes return D&D-style ability *scores* (e.g. 16) instead of PF2e *modifiers* (-5..+5); values > 5 are coerced via `(score - 10) // 2` then clamped.
- Batch size is 10 pairs/run (`BATCH_SIZE`); LLM offline → log WARN and return `(0, 0)` without failing the task.

**State files** (`state/`, gitignored): `scenarios.json` (active campaign scenarios with `id`/`name`/`description`/`arc`), `processed-npcs.json` (composite-key index of what's been generated, status `ok`/`error-llm`/`error-image`/`error-write`). Successful runs also flip `agents.lore` to `done` in the shared `system/state/inbox-queue.json`.

**Output convention:** `01-Processing/npc-{image-slug}-{arc}.md`, frontmatter `status: draft`, `quality: 0`, `reviewed: false` — this agent never sets those to approved/true (`agents/shared/vault_guard.py` enforces this repo-wide). The scenario's own wikilink is always the first entry in `relationships`.

## Vault rules that apply here (see root `AGENTS.md` / `CLAUDE.md` for full vault spec)

- `type: npc` entities must link to at least one location, faction, or quest — never orphaned.
- Level 1–20, ability modifiers -5..+5 — validated by `NPCLLMOutput` (`agents/shared/models.py`) and `_normalize_stats`.
- Only `quality >= 7` and human-set `status: approved` may ever reach `02-Library/`; this agent only writes to `01-Processing/`.
- Don't contradict existing `02-Library/` canon — that's why `load_canon_context` exists and is fed into every prompt.
