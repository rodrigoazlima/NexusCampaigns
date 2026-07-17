# Worker: thumbnails

Status: SPEC · Kind: **queue consumer** · Replaces: `thumbnails-agent`
Current code: `nexus/tasks/thumbnails_agent.py`

## Role

Pre-generate 320px-wide webp thumbnails for every image entry in the inbox
queue into `system/state/thumbs/<sha1(queue-key)>.webp`. Dashboard's
`/api/image?thumb=1` serves them, falling back to the original.

Simplest consumer in the set - pure cache warmer: no vault writes, no queue
slot of its own, no commits.

## Worker mapping

```python
name = "thumbnails"; kind = "queue"

def pending() -> list[WorkItem]:
    # queue image entries whose thumb file is missing → one item each.
    # Plus prune set: thumb files whose queue entry is gone (emitted as
    # items with payload {"action": "prune"}).
    ...

def handle(item) -> WorkResult:
    # generate one webp (Pillow), or unlink one orphan thumb.
    # done  = written/pruned · skip = unreadable image (logged)
    ...
```

No inbox-queue slot is added for thumbnails - the thumb file's existence IS
the done-marker (cheap to stat, self-healing when a thumb is deleted). This
preserves current behavior and keeps the queue schema untouched.

## State

| Now | Target |
|-----|--------|
| `system/state/thumbs/` (cache) | unchanged |
| `agents/thumbnails/state/` (logs only) | `system/state/workers/thumbnails/logs/` |

## Config

```yaml
workers:
  thumbnails:
    kind: queue
    batch_size: 10
    commit_scope: []        # everything gitignored
```

## Errors / retries

- Corrupt/unreadable image → `skip` (not `error`): retrying cannot fix the
  source file, and the dashboard fallback covers it. Detail logs the path.
- Pillow missing → `pending()` returns `[]` and logs WARN once per session.

## Deletions when migrated

- `agents/thumbnails/` (agent.json, AGENT.md, prompts/system.md, state/).
- `_AGENT_JSON_SPECS["thumbnails"]`.
- `nexus/tasks/thumbnails_agent.py` → `nexus/workers/thumbnails.py`.
- No `_PRECONDITIONS` entry exists (interval-only today) - the worker gains
  a real pending-check, dropping the run-and-scan-everything cycle.

## Migration steps

1. Move module; split scan into `pending()` (missing thumbs + orphans) and
   `handle()` (one thumb).
2. Move log dir; enable in registry; delete agent folder + spec entry.
3. Tests: thumb generated for new entry, orphan pruned after entry removal,
   corrupt image skips without failing the cycle.

## Acceptance

1. Queue with 15 images, empty thumbs dir, batch_size 10 → cycle 1 writes
   10 thumbs, cycle 2 writes 5, cycle 3 `pending()` = [].
2. Delete a queue entry → its thumb pruned next cycle.
3. Zero commits ever originate from this worker.
