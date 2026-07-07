# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

First-stage agent of the vault pipeline (see repo-root `CLAUDE.md` for the full architecture). Prepares raw `00-Inbox/` material for downstream agents. **No LLM calls** — pure deterministic Python, dispatched via `lm-studio` in `agent.json` only to drive the tool-call loop, not for content generation.

## Commands

```powershell
# Run standalone (bypasses runner scheduling)
python -m nexus.tasks.ingestion_agent

# Run via the shared scheduler (from repo root)
python -m nexus.runner --task ingestion-agent --force

# Relevant tests (repo root)
pytest agents/tests/test_11_ingestion_agent.py
```

## Layout

- `system/src/nexus/tasks/ingestion_agent.py` — all logic; `IngestionAgent(BaseAgent)` + `TOOLS`/`call_tool()` for agentic dispatch.
- `agent.json` — task config (hourly, `lm-studio` dispatch).
- `AGENT.md` — contract: inputs/outputs, `commit_scope`, restrictions (read before changing behavior).
- `prompts/system.md`, `prompts/prompt.md` — instructions for the dispatched model; keep in sync with the step order in `run_batch()`.
- `.agents/shared` → symlink to `agents/shared/` (so `from shared import ...` resolves without a real package copy).
- `.knowledge-base/00-Inbox` → symlink to the vault's real inbox.
- `.system/state` → symlink to `system/state/` (shared `inbox-queue.json` lives here, not under this agent's own `state/`).

## `run_batch()` pipeline order (in `system/src/nexus/tasks/ingestion_agent.py`)

1. `absorb_stray_entries` — move stray top-level vault folders into `00-Inbox/`, only if `registry.yaml`'s `ingestion_options.auto_absorb_stray` is true; otherwise just logs a warning per stray entry so nothing silently vanishes.
2. `strip_emoji_filenames` — idempotent emoji/non-ASCII strip on `00-Inbox/` filenames, collision-safe (timestamp suffix on conflict).
3. `process_docx_files` — installs Pandoc via winget if missing; converts up to `BATCH_SIZE` (10) unprocessed `.docx` → GFM Markdown in `00-Inbox/docs/`, extracting images to `00-Inbox/images/{slug}/` and flattening Pandoc's `media/` subdir with path rewriting in the output Markdown. Tracked in `state/processed-docx.txt` (append-only, one relative path per line).
4. `register_new_files` — scans `00-Inbox/` recursively, adds any file not already a key in `system/state/inbox-queue.json`, typing it `image`/`document`/`other` and initializing per-agent slots via `_make_slots()`. Skips generated `*-token`/`*.token` files. Logs "phantom" entries (queued but missing from disk) without removing them.
5. `_reconcile_slots` — backfills any newly introduced `AgentSlots` fields on existing queue entries, always forcing `ingestion=done` (existence in the queue implies ingestion already ran).

Each step is independently safe to fail — `run_batch()` accumulates `(count, failed)` across all four and does not short-circuit.

## Conventions specific to this agent

- Queue writes (`_save_queue`, `_reconcile_slots`) are atomic: write `.tmp`, then `Path.replace()`.
- `_file_type()` / `IMAGE_EXTS` / `DOCUMENT_EXTS` define the canonical extension→type mapping — downstream agents rely on the slot shape this produces (see `_make_slots()`), so changing type detection or slot defaults is a cross-agent contract change.
- `find_stray_entries()` / `_CANON_VAULT_DIRS` encode the repo-root `CLAUDE.md` vault folder list (`00-Inbox` … `99-Archive`); update both places together if the vault schema changes.
- Never touch `02-Library/`, never delete/rename outside `00-Inbox/` — enforced by convention in code, not by a runtime guard (unlike agents that go through `vault_guard.py`).

## Vault-wide rules (from repo-root `AGENTS.md`)

- `00-Inbox/` subfolders: `images/` (organized by arc), `docs/`, `songs/`, `tokens/` — preserve originals, never modify/delete.
- Agent priority order for the whole pipeline: reusability > consistency > traceability > human review > knowledge-graph connectivity.
- Only humans may set `reviewed: true` / `status: approved` — no agent in this repo does.
- `AGENTS.md`'s own "Ingestion Agent" section (image slug/metadata generation, `agents/vision/state/processed-images.json` updates) describes an **older spec**, not this implementation — current code (`system/src/nexus/tasks/ingestion_agent.py`) does filename cleanup + DOCX conversion + queue registration only, no per-image metadata generation (that's the `vision` agent's job now, tracked via `agents/vision/state/processed-images.json`, which this agent's `_reindex_moved_prefix()` patches on stray-absorb moves).
