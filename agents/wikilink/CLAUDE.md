# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this agent does

Wikilink Agent (task id `wikilink-agent`). Inserts cross-reference `[[slug]]` wikilinks into the
`## Related` section of approved `02-Library/` entities. **No LLM calls** — pure scoring/regex logic
in `system/src/nexus/tasks/wikilink_library.py`. Runs hourly via the runtime scheduler, or standalone.

## Commands

```powershell
# Run directly (from repo root, not this dir — module needs agents/ on sys.path)
python -m nexus.tasks.wikilink_library
python -m nexus.tasks.wikilink_library --min-score 2 --max-links 5

# Run via the runtime scheduler instead of standalone
python -m nexus.runner --task wikilink-agent --force

# Tests (from repo root)
pytest agents/tests -k wikilink
```

## Architecture

- `system/src/nexus/tasks/wikilink_library.py` — everything lives in this one file:
  - `WikilinkResolver` implements `IWikilinkResolver` (see `agents/shared/interfaces.py`)
  - `build_slug_index()` — maps every `02-Library/**/*.md` filename stem → path
  - `_score()` — pairwise score between source/target entity: shared tags (+1 each, cap 3),
    explicit wikilink already present above `## Related` (+3), verbatim slug/name mention in
    body (+2/+1), shared keyword overlap (+1 each, cap 2), plus `required_type_boost()` (+5) when
    a candidate fills a required link per `agents/shared`'s per-type linking rules (NPC→location/
    faction/quest, Quest→NPC+location, etc. — see AGENTS.md "Linking Rules")
  - `insert_wikilinks()` — sorts candidates by score, takes top `MAX_LINKS` (10), splices new
    `[[slug]]` lines into `## Related` (creating the section if absent), atomic tmp-write
  - `main()` / `call_tool()` — two entry points: direct CLI run and the `TOOLS` agentic interface
    (`score_entity_pairs`, `insert_wikilinks`) used when dispatched via `lm-studio` per `agent.json`
- Depends on `agents/shared` (`FrontmatterIO`, `Logger`, `StateStore`, `extract_wikilinks`,
  `has_wikilink`, `slugs_from_relationships`, `required_type_boost`) — read those before changing
  scoring or frontmatter I/O.
- State: `state/wikilink-state.json` tracks per-file `processedAt` / `linksInserted` so repeated
  runs don't reprocess the same file. Batch size is 20 files/run (`BATCH_SIZE`).
- `.knowledge-base/` here is a junction into the vault repo — `02-Library/` is the only directory
  this agent may touch, and only the body (never frontmatter, never new files).

## Hard restrictions (enforced by contract in AGENT.md, not just convention)

- Must not call any LLM inside `wikilink_library.py` itself (the `lm-studio` dispatch just drives
  the two tool calls; scoring/writing is deterministic)
- Must not touch `00-Inbox/` or `01-Processing/`
- Must not modify frontmatter — body only
- Must not create new files — only edits existing `02-Library/*.md` in place
- Must not remove existing wikilinks, only add missing ones
- `commit_scope` (see AGENT.md) is `.knowledge-base/02-Library` only — the runner stages/commits
  just that path after a successful run

## Vault-wide rules relevant to this agent (from repo-root `AGENTS.md` / `CLAUDE.md`)

- `02-Library/` entities are canon once `status: approved` — this agent may add links but must
  never overwrite canon content or set `reviewed`/`status` fields (those are human-only, see
  `agents/shared/vault_guard.py`'s `assert_not_self_approved()`)
- Every entity must end up with at least one outbound link — no orphans in `02-Library/`
  (this is the reason `required_type_boost` exists: it prioritizes filling an entity's
  type-required link category, e.g. NPC needing a location/faction/quest link)
- Slug format is `{type}-{descriptors}.md`; wikilinks (`[[slug]]`) must match the filename stem
  exactly
- All file I/O must use UTF-8 explicitly (see `_atomic_write`'s `encoding="utf-8"`)
