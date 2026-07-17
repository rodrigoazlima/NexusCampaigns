# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this agent does

Wiki Agent compiles raw `00-Inbox/` markdown/docx notes into structured, AGENTS.md-compliant entity drafts in `01-Processing/`. It reads `system/state/inbox-queue.json` for entries with `type=document` and `agents.wiki=pending`, synthesizes via a local LLM using canon context pulled from `02-Library/`, and writes one draft page per source document.

Full contract: `AGENT.md` (frontmatter block - inputs/outputs/responsibilities/restrictions/commit_scope). Read it before touching `tools/compile_wiki.py`. Agent role/workflow for the LLM: `prompts/system.md`.

Note: `AGENT.md` here is the authoritative, current contract. The vault-level `AGENTS.md` "Wiki Agent" section (cross-linking `02-Library/`, updating `04-Relationships/`) describes a different/older responsibility split - don't follow it for this agent; it's stale relative to `AGENT.md`.

## Commands

```powershell
# Run this agent standalone via the shared runner
python -m nexus.runner --task wiki-agent --force

# Run compile_wiki.py's tool functions directly for debugging
python -c "from tools import compile_wiki; compile_wiki.main()"
```

Dispatch is configured in `agent.json` as `lm-studio` (`http://localhost:1234/v1`, model `google/gemma-4-26b-a4b`), but `compile_wiki.py` itself calls **LocalRouter** directly at `http://localhost:8080/v1/chat/completions` - check both are reachable if a run silently no-ops (LocalRouter offline → logs WARN and skips the batch).

## Architecture

- `tools/compile_wiki.py` - all logic. Key constants: `BATCH_SIZE = 5` documents/run, `_MAX_CHARS = 6000` (content truncated with a truncation notice beyond this), 2000ms sleep between LLM calls.
- Pipeline per run: pre-flight check LocalRouter → load `02-Library/` canon (id/type/tags/relationships, capped ~50 entities) as context → load `inbox-queue.json`, filter `type=document` + `agents.wiki=pending`, skip anything already in `state/bad-wiki-docs.txt` → for each: read file, strip HTML (for DOCX-converted sources), skip (mark done, not bad) if <100 chars post-strip, truncate to 6000 chars, call LLM with DM-synthesis prompt enforcing the metadata schema.
- Post-LLM enforcement in `_enforce_and_write` (`tools/compile_wiki.py:149`) hard-overwrites: `status: draft`, `reviewed: false`, `quality: 0`, `source: [filename]`, and validates `type` against the allowed list (`AGENT.md` line 42-ish; falls back to `lore` if invalid) - the LLM output is never trusted for these fields.
- Output path: `01-Processing/{slug}.md`; if the slug already exists, a date suffix is appended (`_unique_output`).
- State: `system/state/inbox-queue.json` (`agents.wiki` flag flipped to `done` per entry on success), `agents/wiki/state/bad-wiki-docs.txt` (permanent failures - read errors, repeated LLM failures - appended, not overwritten).
- On LLM connection error: abort the whole batch and retry next run - do **not** mark files bad for transient outages.
- `commit_scope` (who commits what, enforced by the runner, not this code): only `.knowledge-base/01-Processing`.

## Hard restrictions (see AGENT.md)

- Never touches `02-Library/`, never sets `reviewed: true`, `status: approved`, or `status: review`.
- Never processes queue entries with `type != document`.
- Never invents entity types outside the allowed list; never sets its own quality score above 0.
- Agents in this repo never self-commit - the shared runner (`system/src/nexus/runner.py (run: python -m nexus.runner)`) commits only the paths in `commit_scope`.

## Vault conventions this agent must honor

- Entity id/slug format: `{type}-{descriptors}.md` (e.g. `npc-necromancer-black-hollow.md`). No `final_v2.md`/`newnpc.md`/`Untitled.md`-style names.
- Every draft needs ≥1 outbound `[[wikilink]]` to a related canon entity if one exists in the loaded `02-Library/` context.
- Allowed `type` values: `npc · character · faction · location · city · village · dungeon · item · artifact · quest · encounter · creature · monster · event · religion · organization · timeline · lore`.
