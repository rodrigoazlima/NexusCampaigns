# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this agent is

Canon agent. Validates consistency of **approved** entities in `02-Library/` against each other. Read-only on all vault dirs — never writes/modifies vault content. Produces a `CanonReport` (violations list + scan counts).

Status: **spec-only**. `AGENT.md` (contract) exists; `tools/`, `prompts/`, `agents/` subfolders are empty — `agent.json` dispatch config and `tools/canon_agent.py` implementation not yet written. See "Adding a New Automation" in the root `CLAUDE.md` for the scaffold pattern used by sibling agents (e.g. `agents/review/`).

## Responsibilities (from `AGENT.md`)

- Scan all `.md` in `02-Library/` via `EntityScanner`
- Build slug index (filename stem → path) for wikilink resolution
- Per entity: validate required frontmatter fields (`id`, `type`, `status`, `quality`, `reviewed`, `relationships`); resolve `[[wikilink]]`s against slug index and flag broken ones; flag empty `relationships` as `orphan_entity`; flag duplicate `id`s; warn if `status: approved` but `quality < 7` or `reviewed != true`
- Write report to `state/canon-report-latest.json` and dated archive `state/reports/canon-{YYYY-MM-DD}.json`
- Emit START/DONE log markers

## Restrictions

- Read-only on `02-Library/` — must never write to vault directories
- Must not modify any approved entity without explicit human action
- Must not call any LLM
- `commit_scope` is empty — this agent must never auto-commit (it produces no vault content)

## Contract & shared types (`agents/shared/`)

- `interfaces.py::ICanonValidator.validate(library_dir: Path) -> CanonReport` — the contract this agent's tool implementation must satisfy
- `models.py`: `CanonViolationType` enum (`broken_wikilink`, `missing_relationship`, `duplicate_id`, `missing_required_field`, `orphan_entity`), `CanonViolation` (entity_id, path, violation_type, detail), `CanonReport` (date, generatedAt, violations, entities_scanned, entities_clean)
- `entity_scanner.py::EntityScanner` — walks vault dirs yielding `(path, EntityFrontmatter, body)`; skips files that fail frontmatter validation silently. Also provides `scan_ids()` (id → path) and `scan_slugs()` (filename stem → path) — use `scan_slugs()` for wikilink resolution and `scan_ids()` for duplicate-id detection.
- `vault_guard.py` (`IVaultGuard`) — not needed here since canon never writes, but other agents in this pipeline must call `assert_writable()` / `assert_not_self_approved()` before frontmatter writes; `status: approved` and `reviewed: true` are human-only fields.

## Vault rules relevant to canon checks (from root `AGENTS.md`)

- Only `quality >= 7` **and** `reviewed: true` **and** `status: approved` entities belong in `02-Library/`
- Every entity needs ≥1 outbound wikilink — no orphans allowed
- Allowed `type` values: `npc · character · faction · location · city · village · dungeon · item · artifact · quest · encounter · creature · monster · event · religion · organization · timeline · lore`
- Slug/filename format: `{type}-{descriptors}.md` (e.g. `npc-necromancer-black-hollow.md`); wikilinks must match filename stem exactly
- Preferred link direction (useful when distinguishing "broken" vs "just thin" relationships): NPC → location/faction/quest; Quest → NPC + location; Location → NPC/faction; Faction → NPC + location

## Commands (root-level, run from repo root)

```powershell
pytest agents/tests/test_*canon* -k canon      # once tests exist for this agent
python -m nexus.runner --task canon-agent --force   # once agent.json exists
```

No dedicated build/lint for this folder — it's pure Python under the shared pytest suite at repo root.
