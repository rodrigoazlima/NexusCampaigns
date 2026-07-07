# Agents & Workers List

Post-refactor inventory. LLM agents are discovered from `agents/*/agent.json`
(scheduled by `nexus.runner` in `registry.yaml` `execution_order`). Static
work runs as in-process **workers** (`nexus.workers.*`), configured in the
`workers:` block of `agents/registry.yaml` — no agent.json, no subprocess.

## LLM agents

| # | Agent | Task ID | Entry point | Interval | Purpose |
|---|-------|---------|-------------|----------|---------|
| 1 | vision | `vision-agent` | `agents/vision/tools/classify_images.py` | 15 min | Image classification via local vision LLM (LM Studio) |
| 2 | lore | `lore-agent` | `agents/lore/tools/generate_npcs.py` | 15 min | Generate NPC drafts from classified images |
| 3 | wiki | `wiki-agent` | `agents/wiki/tools/compile_wiki.py` | 15 min | Compile enriched drafts into wiki entity pages in `01-Processing/` |
| 4 | classification | `classification-agent` | `agents/classification/tools/enrich_tags.py` | 15 min | Enrich draft tags and infer entity type |

## Workers (static, in-process)

| Worker | Kind | Trigger | Purpose |
|--------|------|---------|---------|
| ingestion | queue (producer) | `pending()` every cycle | Emoji-strip filenames, convert DOCX, register inbox queue entries |
| thumbnails | queue | `pending()` every cycle | Pre-generate 320px webp thumbnails for inbox images |
| token | queue | `pending()` every cycle | Generate 512×512 VTT tokens from classified portraits |
| wikilink | queue | `pending()` every cycle (mtime-derived) | Link `02-Library/` entities via wikilinks |
| shortfiles | queue | `pending()` every cycle (seen.json-derived) | Flag drafts under 10 body lines for reprocessing |
| report | scheduled | every 15 min | Pipeline health + pending-review report |
| cleanup | scheduled | daily | Prune old logs/reports, trim agent-metrics history |
| maintenance | scheduled + signal | daily, or on `worker-error` signal | Stale locks, missing dirs, queue validation, poison-pill report |

Also in `nexus.tasks` but not scheduled: `remove_background` (manual utility).

## Running

```powershell
python -m nexus.runner --once                        # one scheduling cycle (agents + workers)
python -m nexus.runner --task <task-id> --force      # single LLM agent, skip checks
python -m nexus.runner --task worker:<name> --force  # single worker, skip checks
python -m nexus.workers.<name>                       # worker directly (one pending/handle pass)
```

`agent.json` is machine-local (gitignored) and exists for LLM agents only; the
maintenance worker regenerates missing ones from `_AGENT_JSON_SPECS` in
`system/src/nexus/workers/maintenance.py`. Worker config is git-tracked in
`agents/registry.yaml` — nothing machine-local to regenerate.
