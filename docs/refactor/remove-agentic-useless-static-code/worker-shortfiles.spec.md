# Worker: shortfiles

Status: SPEC · Kind: **queue consumer** (derived pending set) · Replaces: `review-agent-short-files`
Current code: `nexus/tasks/flag_short_files.py`

## Role

Draft QA gate: scan `01-Processing/` for `.md` drafts with fewer than
`MIN_BODY_LINES` (10) body lines; set `needs_reprocessing: true` in
frontmatter and inject `suggestedQuality: 0` when `quality: 0` and no
suggestion exists. Flags feed the LLM agents' rerun logic and the human
review dashboard.

## Worker mapping

```python
name = "shortfiles"; kind = "queue"

def pending() -> list[WorkItem]:
    # today's _processing_has_files sharpened: 01-Processing .md files
    # not yet flagged and not previously measured-OK at current mtime
    # (tracked in worker state - today the task rescans everything).
    ...

def handle(item) -> WorkResult:
    # one draft: count body lines → under threshold: write flags
    # (frontmatter write through FrontmatterIO), update inbox-queue rerun
    # slot via locked_update_queue_entry where entry exists.
    # done = flagged · skip = long enough (recorded with mtime)
    ...
```

## Guard rules (carried over)

- Never writes `02-Library/`.
- May write `01-Processing/` frontmatter fields `needs_reprocessing`,
  `suggestedQuality` **only** - never `status`, `reviewed`, `quality`
  (vault-guard human-only fields).

## State

| Now | Target |
|-----|--------|
| logs `system/state/review/logs/` | `system/state/workers/shortfiles/logs/` |
| (no scan state today - full rescan) | `system/state/workers/shortfiles/seen.json` (path → {mtime, verdict}) |

`seen.json` is the one behavior improvement: today every run re-reads every
draft; the worker skips unchanged files.

## Config

```yaml
workers:
  shortfiles:
    kind: queue
    batch_size: 50               # cheap per-item work
    interval_seconds: 3600
    commit_scope: [".knowledge-base/01-Processing"]
```

## Errors / retries

- Unparseable frontmatter → `skip` + detail (matches wikilink policy).
- Contract poison-pill guard applies via `seen.json` attempt counter.

## Deletions when migrated

- `agents/review/` - **only after worker-report also migrates** (folder is
  shared by both review tasks). Until then: remove only the
  `review-agent-short-files` entry from its agent.json.
- `runner._PRECONDITIONS["review-agent-short-files"]` + `_processing_has_files`.
- `_AGENT_JSON_SPECS["review"]` short-files entry.
- `nexus/tasks/flag_short_files.py` → `nexus/workers/shortfiles.py`.

## Migration steps

1. Move module; add `seen.json` skip layer; per-file `handle()`.
2. Enable in registry; strip task from review agent.json + spec entry.
3. Tests: `tests/test_15_flag_short_files.py` re-points; add: unchanged
   file not re-read (mtime cache hit), flagged file's `status` untouched.

## Acceptance

1. 12-line draft → untouched, recorded OK. 6-line draft → flagged +
   suggestedQuality injected, queue rerun slot set, commit stages only
   `01-Processing`.
2. Second cycle with no edits → `pending()` = [].
3. Draft edited after flagging → re-measured next cycle.
