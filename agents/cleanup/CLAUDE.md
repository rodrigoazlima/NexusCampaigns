# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this agent does

Cleanup agent. Daily housekeeping, no LLM calls, no vault content touched. See `AGENT.md` for full contract (inputs/outputs/restrictions/commit_scope — read before modifying).

`tools/cleanup_agent.py` does three things each run:
1. `purge_logs` — delete `.log` files older than `cleanupDays` under every `agents/*/state/logs/`
2. `purge_reports` — delete `.json` report files older than `cleanupDays` under every `agents/*/state/reports/`
3. `trim_metrics` — trim `agents/runtime/state/agent-metrics.json` per-agent `runs` list to last `MAX_METRIC_RUNS` (100)

Then writes `state/reports/cleanup-{YYYY-MM-DD}.json` and logs START/DONE via `shared.logger.Logger`.

`cleanupDays` lives in `agent.json` top-level field (default 90, see `_load_cleanup_days()`). Dispatch is `lm-studio` (local model, see `agent.json`) — the model only calls the three tools + self-management tools in `TOOLS`; it does not decide what to delete.

## Commands

```powershell
# Run this agent standalone (bypasses runner due/precondition checks)
python agents/runtime/tools/runner.py --task cleanup-agent --force

# Run the tool script directly
python agents/cleanup/tools/cleanup_agent.py

# Tests (from repo root)
pytest agents/tests/test_11_ingestion_agent.py -k cleanup   # if a cleanup test exists; check agents/tests/ for exact filename
```

## Rules specific to this agent

- Only ever deletes files inside `*/state/logs/` and `*/state/reports/` directories — never touches `00-Inbox/`, `01-Processing/`, `02-Library/`, or any vault content (`.knowledge-base/`)
- Must never delete `tasks-state.json`, `agent.json`, or other state JSON (`inbox-queue.json`, `processed-*.json`, etc.) — only `.log` files and dated report `.json` files qualify
- Writes to `agent-metrics.json` use the atomic tmp-write-then-`.replace()` pattern (`_write_report`, `trim_metrics`) — follow this pattern for any new state writes in this repo, not just here
- Must not run more than once per calendar day — enforced by the runner's interval check (`intervalSeconds: 86400` in `agent.json`), not by this script
- Produces no vault content, so `commit_scope` in `AGENT.md` is empty — this agent must never auto-commit

## Repo-wide context (from root CLAUDE.md / AGENTS.md)

- This vault is a Dungeon Master Nexus Campaigns knowledge base with pipeline `00-Inbox → 01-Processing → (human review) → 02-Library → 03-Campaigns/04-Relationships/05-Assets`
- `agents/runtime/tools/runner.py` is the only "static" orchestrator; every other `agents/<name>/` is a spec-driven agent
- Every agent subclasses `BaseAgent` (`agents/shared/interfaces.py`) with `bootstrap()` → `run_batch()` → `execute()` lifecycle logging START/DONE — this agent's script follows the same log-marker convention via `Logger`, though it predates/bypasses the `BaseAgent` class since it needs no LLM
- Security boundary (`agents/shared/vault_guard.py`) — `assert_writable()` / `assert_not_self_approved()` before frontmatter writes — does not apply here since this agent never writes vault frontmatter
- Read `docs/specs/agents/agent-*.spec.md` for the authoritative contract of any agent before changing its behavior
