# Agents List

Inventory of pipeline agents discovered from `agents/*/agent.json` (scheduled by
`nexus.runner` in `registry.yaml` `execution_order`). Static tasks run as
`python -m nexus.tasks.<module>` (no LLM); LLM agents run their own
`agents/<name>/tools/` script.

## Scheduled agents

| # | Agent | Task ID | Kind | Entry point | Interval | Purpose |
|---|-------|---------|------|-------------|----------|---------|
| 1 | repair | `repair-agent` | static | `nexus.tasks.repair_agent` | 24 h | Pipeline self-maintenance — stale locks, missing dirs, queue validation, agent.json scaffolding |
| 2 | ingestion | `ingestion-agent` | static | `nexus.tasks.ingestion_agent` | 15 min | Vault ingestion — emoji-strip filenames, convert DOCX, register inbox queue |
| 3 | vision | `vision-agent` | **LLM** | `agents/vision/tools/classify_images.py` | 15 min | Image classification via local vision LLM (LM Studio) |
| 4 | lore | `lore-agent` | **LLM** | `agents/lore/tools/generate_npcs.py` | 15 min | Generate NPC drafts from classified images |
| 5 | token | `token-agent` | static | `nexus.tasks.generate_tokens` | 15 min | Generate 512×512 VTT tokens from classified portrait images (face detect + moldura) |
| 6 | wiki | `wiki-agent` | **LLM** | `agents/wiki/tools/compile_wiki.py` | 15 min | Compile enriched drafts into wiki entity pages in `01-Processing/` |
| 7 | classification | `classification-agent` | **LLM** | `agents/classification/tools/enrich_tags.py` | 15 min | Enrich draft tags and infer entity type |
| 8 | review | `review-agent` | static | `nexus.tasks.daily_report` | 15 min | Daily pipeline health + pending-review report |
| 8 | review | `review-agent-short-files` | static | `nexus.tasks.flag_short_files` | 15 min | Flag drafts under 10 body lines for reprocessing |
| 9 | wikilink | `wikilink-agent` | static | `nexus.tasks.wikilink_library` | 1 h | Link `02-Library/` entities via wikilinks |
| 10 | cleanup | `cleanup-agent` | static | `nexus.tasks.cleanup_agent` | 24 h | Prune old logs/reports, trim agent-metrics history |
| 11 | thumbnails | `thumbnails-agent` | static | `nexus.tasks.thumbnails_agent` | 1 h | Pre-generate 320px webp thumbnails for inbox images |

Also in `nexus.tasks` but not scheduled: `remove_background` (manual utility).

## Spec'd but not scheduled (no `agent.json`)

| Agent | Notes |
|-------|-------|
| adventure-builder | Builds campaign material from Library entities |
| canon | Canon validation of approved content |
| curator | Curates `01-Processing/` drafts |
| deduplication | Detects duplicate inbox/processing content |
| encounter-builder | Builds encounters from Library entities |
| relationship | Generates `04-Relationships/` graphs |
| runtime | Not an agent — home of scheduler state (`agents/runtime/state/`) |
| search | Search over processing/library |
| session-builder | Builds session prep from campaigns |

## Running

```powershell
python -m nexus.runner --once                      # one scheduling cycle
python -m nexus.runner --task <task-id> --force    # single task, skip checks
python -m nexus.tasks.<module>                     # static task directly
```

`agent.json` is machine-local (gitignored); the repair agent regenerates
missing ones from `_AGENT_JSON_SPECS` in `system/src/nexus/tasks/repair_agent.py`.
