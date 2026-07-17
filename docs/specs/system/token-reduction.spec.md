# Spec - Token Reduction via Precondition-Gated Dispatch

**Version:** 1.0
**Date:** 2026-06-14

---

## Problem

Agents run on fixed intervals (hourly/daily) regardless of whether they have actual work.
An agent dispatched with no pending items still consumes tokens on:
- System prompt loading
- Tool calls (`scan_pending`, `load_canon_context`, etc.)
- LLM reasoning over an empty result set

With 10+ agents running hourly, idle dispatch compounds into significant wasted spend.

---

## Solution

Before dispatching any agent, the runner evaluates a **precondition**: a fast local check
(no LLM, no subprocess) that answers "is there actual work to do?"

If the precondition returns `False`, the agent is skipped entirely - no dispatch, no tokens consumed.
`lastRun` is **not updated**, so the agent will be re-evaluated next cycle.

---

## Implementation

**File:** `agents/runtime/tools/runner.py`

**Hook in `run_cycle()`:**
```
is_due? → no  → skip (existing)
         → yes → _check_preconditions(task_id) → False → skip (no tokens)
                                                → True  → dispatch
```

**`_check_preconditions(task_id)`** looks up `_PRECONDITIONS[task_id]()` and returns the result.
Unknown task IDs default to `True` (always run) to avoid breaking new agents.

---

## Precondition Table

| Agent | Task ID | Precondition | Data Source |
|-------|---------|--------------|-------------|
| Ingestion | `ingestion-agent` | `00-Inbox/images/` or `00-Inbox/docs/` contains at least one processable file | Filesystem scan |
| Vision | `vision-agent` | `inbox-queue.json` has ≥1 entry with `agents.vision == "pending"` | `system/state/inbox-queue.json` |
| Lore | `lore-agent` | `inbox-queue.json` has ≥1 entry with `agents.lore == "pending"` | `system/state/inbox-queue.json` |
| Classification | `classification-agent` | `inbox-queue.json` has ≥1 entry with `agents.classification == "pending"` | `system/state/inbox-queue.json` |
| Wiki | `wiki-agent` | `inbox-queue.json` has ≥1 entry with `agents.wiki == "pending"` | `system/state/inbox-queue.json` |
| Token | `token-agent` | `processed-images.json` has ≥1 image with `status==ok`, `isToken==false`, not in `generated-tokens.json` | `agents/vision/state/processed-images.json`, `agents/token/state/generated-tokens.json` |
| Wikilink | `wikilink-agent` | `02-Library/*.md` has ≥1 file absent from `wikilink-state.json` OR modified after its `processedAt` timestamp | `02-Library/`, `agents/wikilink/state/wikilink-state.json` |
| Review (short files) | `review-agent-short-files` | `01-Processing/` contains ≥1 `.md` file | Filesystem scan |
| Cleanup | `cleanup-agent` | Any log file in `agents/runtime/state/logs/` older than 7 days | Filesystem `mtime` scan |
| Review | `review-agent` | **Always runs** (health monitor - skipping defeats its purpose) | - |
| Repair | `repair-agent` | **Always runs** (health monitor - skipping defeats its purpose) | - |

---

## Ingestion File Types

Ingestion precondition triggers on:

| Folder | Extensions |
|--------|-----------|
| `00-Inbox/images/` | `.jpg` `.jpeg` `.png` `.webp` `.gif` `.bmp` `.tiff` |
| `00-Inbox/docs/` | `.docx` `.doc` `.pdf` `.md` `.txt` |

---

## Precondition Failure Behaviour

If the precondition check itself throws an exception (corrupt state file, permission error, etc.):
- Warning logged: `Precondition check failed for {task_id}: {exc} - running anyway`
- Agent dispatches normally
- No silent skip on error

---

## Expected Token Savings

Idle vault (no new inbox files, no pending queue items):

| Agent | Runs/day before | Runs/day after |
|-------|----------------|----------------|
| Ingestion | 24 | 0 |
| Vision | 24 | 0 |
| Lore | 24 | 0 |
| Classification | 24 | 0 |
| Wiki | 24 | 0 |
| Token | 24 | 0 |
| Wikilink | 24 | 0 |
| Review (short) | 96 | 0 |
| Cleanup | 1 | 0–1 |
| **Review** | 96 | **96** (always) |
| **Repair** | 96 | **96** (always) |

During active processing (e.g. 10 new images dropped):

| Phase | Agents that fire |
|-------|-----------------|
| Files land in `00-Inbox/` | Ingestion |
| After ingestion queues items | Vision, Lore, Classification |
| After vision classifies | Token, Lore (via signal) |
| After lore generates NPCs | Classification |
| After docs queued | Wiki |
| After files reach `02-Library/` | Wikilink |

---

## Adding Preconditions for New Agents

Add an entry to `_PRECONDITIONS` in `runner.py`:

```python
_PRECONDITIONS["my-new-agent"] = lambda: _inbox_has_slot("my_slot")
```

Or define a dedicated check function for more complex conditions.
Omitting the entry defaults to **always run**.
