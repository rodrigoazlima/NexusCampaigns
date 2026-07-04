# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this agent is

Repair agent — pipeline maintenance, no LLM calls, no vault content changes. Runs every 15 min via the shared `agents/runtime` scheduler, dispatched from `agents/repair/agent.json` (gitignored, machine-local) against the spec in `AGENT.md`.

Full behavioral contract lives in `AGENT.md` (frontmatter: inputs/outputs/responsibilities/restrictions) and `prompts/system.md` (ordered workflow steps 0–7). Read both before changing `tools/repair_agent.py` — they are the source of truth the LLM dispatcher follows; code must match them.

## Running it

```bash
python -m agents.repair.tools.repair_agent    # from nexus/ project root
```

Runs all steps unconditionally (`main()`), writes daily log to `state/logs/repair_agent_YYYY-MM-DD.log`, and a report to `agents/review/state/reports/repair-YYYY-MM-DD.json`. No CLI args, no config needed for standalone runs — `_run_step()` isolates each step so one failure (e.g. no git repo, dashboard down) doesn't block the rest.

No test suite exists for this agent (`agents/tests/` has none named repair). Verify changes by running the script directly and inspecting the report JSON / log tail.

## Architecture: steps and their guardrails

Steps run in fixed order in `main()`, each wrapped by `_run_step()` (catch-log-continue, never raises past this boundary):

1. `_git_update` — fetch + `pull --ff-only`; skipped if `.git` absent; failure non-fatal.
2. `_parse_error_patterns` — regex-scans last 24h of `agents/runtime/state/logs/automation.log` for `stale-lock` / `missing-directory` / `missing-image-ref` labels (see `_ERROR_PATTERNS`).
3. `_remove_stale_lock` — deletes `runner.lock` only if `startedAt` age > 1800s.
4. `_generate_missing_agent_configs` — scaffolds `agents/<name>/agent.json` from the hardcoded `_AGENT_JSON_SPECS` table when absent. This exists because `agent.json` is gitignored (machine-local dispatch config); without it a fresh checkout has zero agents dispatching. **When adding a new agent to the pipeline, add its spec here too** or it silently never runs after a fresh clone.
5. `_create_missing_dirs` — creates dirs from `shared.defaults.REQUIRED_DIRS`.
6. `_ensure_agent_relation_links` — recreates any deleted `agents/<name>/<related-path>` junction from the hardcoded `_AGENT_RELATIONS` table (mirrors `setup-service.ps1`'s `Ensure-AgentRelationLinks`; source of truth is `docs/specs/agents/agent-relationships.md`). Includes `repair` itself, so a broken `agents/repair/agents/*` or `agents/repair/system` link self-heals on the next cycle. Only acts when the path is **completely absent** — an intact junction, a real directory, or a stray file at that path is left untouched, never repointed or removed. **When adding a new agent relationship, update the table here, in `setup-service.ps1`, and in `docs/specs/agents/agent-relationships.md` together.**
7. `_validate_image_refs` — SHA256 identity check against `agents/vision/state/processed-images.json`; prunes entries whose file is gone, flags (does not delete) entries with a hash mismatch as `status: failed` to preserve audit trail. Rebuilds `pathIndex` on any change, atomic write via `.tmp` + `replace`.
8. `_detect_overdue_agents` — cross-references `tasks-state.json` `lastRun` against every `agents/*/agent.json` `intervalSeconds`; overdue = elapsed > 2× interval. Report-only.
9. `_check_dashboard_health` — reads `PORT` from `system/.env.local` (fallback 48080), TCP-probes then HTTP GETs the dashboard. Report-only, no fix applied.
10. `_write_repair_report` — atomic write of the consolidated JSON report.

`repairs_applied` total (logged via `log.done(..., count=repairs)`) sums steps 3, 4, 5, 6, 7 — NOT the report-only steps 8/9.

## Hard restrictions (enforced by convention, not code)

- Never call an LLM.
- Never modify `02-Library/`, delete from `00-Inbox/`, or touch vault content files (`.md`, images) beyond the SHA256-driven prune/flag in step 7.
- Never auto-commit — this agent has no `commit_scope`.
- The only file this agent may delete is `runner.lock` (and only when stale).
- `_ensure_agent_relation_links` may only *create* junctions at absent paths — never delete, repoint, or overwrite anything that already exists there (that's the point: recover destroyed links, don't clobber user data).

## Conventions inherited from the vault (`agents/shared/`)

- All JSON state writes must be atomic: write to `.tmp`, then `Path.replace()` — see `_validate_image_refs` and `_write_repair_report` for the pattern to copy.
- Logging goes through `shared.Logger` (`agents/shared/logger.py`): per-task daily log + shared `automation.log`, `log.start()`/`log.done()` bookend each run.
- Tool modules (`tools/*_agent.py`) must expose `TOOLS: list[dict]` (Anthropic tool schema) and `call_tool(name, args, context) -> str`; self-management tools (`write_log`, `read_state`, `write_state`, etc.) come free via `shared.agent_tools.SELF_MANAGEMENT_TOOLS` / `call_self_management_tool` — check there before adding a new tool that might already be covered.
