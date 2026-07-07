# Worker: token

Status: SPEC · Kind: **queue consumer** · Replaces: `token-agent`
Current code: `nexus/tasks/generate_tokens.py`

## Role

Generate 512×512 circular VTT tokens from vision-classified portrait images:
face detection (MTCNN → OpenCV Haar → upper-center crop fallback), moldura
ring composition (inner radius auto-detected from frame alpha; per-type
override via config `moldura_by_type`), output next to source as
`<stem>-token.png`.

## Worker mapping

```python
name = "token"; kind = "queue"

def pending() -> list[WorkItem]:
    # today's _token_has_pending expanded to items: queue entries where
    #   agents.token == "pending" AND agents.vision == "done"
    #   AND vision type is token-eligible (portrait/character)
    # payload carries the vision classification entry (sha, type, face box)
    ...

def handle(item) -> WorkResult:
    # one image → detect face → compose moldura → save token →
    # update generated-tokens index (sha256 key; "path:" fallback) →
    # set queue slot token=done (or skip for ineligible type)
    ...
```

Carried-over safeguards (must survive verbatim):
- purge stale generated-tokens entries whose tokenPath is gone;
- never process stems ending `-token` / containing `.token`;
- store face box back into vision state via `_store_face`.

## State

| Now | Target |
|-----|--------|
| `agents/token/state/generated-tokens.json` | `system/state/workers/token/generated-tokens.json` |
| reads `agents/vision/state/processed-images.json` | unchanged (vision stays an agent) |
| moldura frames `05-Assets/tokens/frames/` | unchanged |

The maintenance worker's image-ref validation and the runner's old
`_token_has_pending` both read `generated-tokens.json` — update both paths
in the same commit.

## Config

```yaml
workers:
  token:
    kind: queue
    batch_size: 10
    commit_scope: [".knowledge-base/00-Inbox/images"]   # tokens written next to sources
    options:
      moldura_by_type: {}      # carried over from agent.json config
```

`options` is the worker-specific escape hatch (contract allows an opaque
`options:` dict passed to the worker constructor).

## Errors / retries

- Face detection failure is NOT an error — fallback chain ends in
  upper-center crop (current behavior). `error` only for I/O failures.
- deepface/tf-keras import failure → `pending()` returns `[]`, WARN once —
  heavyweight deps stay optional exactly as today.
- Poison-pill guard per contract; `reruns.token` already exists in entries.

## Deletions when migrated

- `agents/token/` (agent.json, AGENT.md, prompts/, state/, assets/ — move
  `assets/frame.png` reference check to 05-Assets path first).
- `runner._PRECONDITIONS["token-agent"]` + `_token_has_pending`.
- `_AGENT_JSON_SPECS["token"]`.
- `nexus/tasks/generate_tokens.py` → `nexus/workers/token.py`.
- `nexus/tasks/remove_background.py` stays in `nexus.tasks` (manual utility,
  documented in agents-list).

## Migration steps

1. Move module; `pending()` from the eligibility scan, `handle()` from the
   per-image body of the batch loop.
2. Move `generated-tokens.json`; update maintenance-worker path in same
   commit.
3. Enable in registry; delete agent folder, precondition, spec entry.
4. Tests: `tests/test_token_agent.py` + `tests/test_10_generate_tokens.py`
   re-point imports; add slot-lifecycle test (pending→done, ineligible→skip).

## Acceptance

1. Entry with vision=done, type=portrait → token file written, index keyed
   by sha256, slot done, commit stages only `00-Inbox/images`.
2. Entry type=battlemap → slot skip, no file.
3. Missing moldura frame → item `error`, other items in batch unaffected.
