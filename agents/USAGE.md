# Agent Usage Guide

How to invoke, configure, debug, and extend each agent.

---

## Quick Reference

| Agent | Trigger | Tool | Manual Run |
|-------|---------|------|-----------|
| orchestrator | Windows Task Scheduler | `runner.ps1` | `pwsh agents/runtime/tools/runner.ps1` |
| ingestion | runner (1 h) | `11-ingestion-agent.ps1` | `pwsh agents/ingestion/tools/11-ingestion-agent.ps1` |
| vision | runner (1 h) | `06-classify-images.ps1` | `pwsh agents/vision/tools/06-classify-images.ps1` |
| lore | runner (1 h) | `09-generate-npcs.ps1` | `pwsh agents/lore/tools/09-generate-npcs.ps1` |
| token | runner (1 h) | `10-generate-tokens.ps1` | `pwsh agents/token/tools/10-generate-tokens.ps1` |
| wiki | runner (1 h) | `03-compile-wiki.ps1` | `pwsh agents/wiki/tools/03-compile-wiki.ps1` |
| classification | runner (1 h) | `04-enrich-tags.ps1` | `pwsh agents/classification/tools/04-enrich-tags.ps1` |
| review | runner (15 min) | `08-daily-report.ps1` | `pwsh agents/review/tools/08-daily-report.ps1` |

> **Note:** During Phase 1–2 migration, tools still live in `system/`. Paths above reflect the Phase 2 target.

---

## Orchestrator

**Purpose:** Dispatcher. Runs every 1 minute via Windows Task Scheduler. Checks which agents are due and invokes them sequentially.

### Install / Register

```powershell
# Run once as Administrator
pwsh agents/runtime/tools/register-tasks.ps1
```

### Uninstall

```powershell
pwsh agents/runtime/tools/deregister-tasks.ps1
```

### Manual dispatch

```powershell
pwsh agents/runtime/tools/runner.ps1
```

### State files

| File | Purpose |
|------|---------|
| `state/agent.json` | Agent registry — ids, script paths, intervals |
| `state/tasks-state.json` | Last-run timestamps per agent |
| `state/settings.json` | Task Scheduler config (task name, interval minutes) |
| `state/logs/automation.log` | Master log — all agents, all runs |
| `state/logs/runner_YYYY-MM-DD.log` | Daily runner log |

### Add / remove an agent from schedule

Edit `state/agent.json`:

```json
{
  "tasks": [
    {
      "id": "my-new-agent",
      "script": "agents/my-new-agent/tools/my-tool.ps1",
      "intervalSeconds": 3600,
      "description": "What it does"
    }
  ]
}
```

Add matching entry to `state/tasks-state.json`:

```json
{
  "my-new-agent": { "lastRun": "1970-01-01T00:00:00.0000000Z" }
}
```

### Troubleshooting

| Symptom | Check |
|---------|-------|
| Runner not firing | Task Scheduler → `pathway-kb-runner` → Last Run Result |
| Agent skipped | `state/tasks-state.json` — lastRun too recent vs intervalSeconds |
| Lock stuck | Delete `state/runner.lock` if older than 30 min |
| Git push failing | Check remote auth; runner pushes after every agent run |

---

## Ingestion Agent

**Purpose:** Stage 1 of the pipeline. No LLM. Normalizes inbox, converts DOCX, registers files.

### What it does each run

1. Strips emoji from filenames in `00-Inbox/` (idempotent)
2. Converts `.docx` files to GFM Markdown via Pandoc; extracts images to `00-Inbox/images/{slug}/`
3. Registers all new `00-Inbox/` files into `system/state/inbox-queue.json` with agent slots

### Prerequisites

- **Pandoc** — auto-installed via `winget` if missing

### State files

| File | Purpose |
|------|---------|
| `state/processed-docx.txt` | Skip list — DOCX files already converted |
| `system/state/inbox-queue.json` | Per-file agent pipeline status (owned by ingestion) |

### inbox-queue.json schema

```json
{
  "00-Inbox\\images\\A5\\npc.jpg": {
    "ingestedAt": "2026-06-03T12:00:00Z",
    "type": "image",
    "agents": {
      "vision": "pending",
      "lore": "pending",
      "classification": "pending"
    }
  }
}
```

Agent slot values: `pending` | `done` | `skip`

### Force re-process a DOCX

Remove the file path from `state/processed-docx.txt`, then run the agent.

### Troubleshooting

| Symptom | Check |
|---------|-------|
| DOCX not converted | Pandoc installed? `pandoc --version` |
| File not appearing in queue | Must be inside `00-Inbox/` — agent only scans that dir |
| Emoji not stripped | File may have already-clean name; check log for "already clean" |

---

## Vision Agent

**Purpose:** Classifies RPG images using Qwen3-VL. Writes draft entities to `01-Processing/`.

### Prerequisites

- **LM Studio** running at `localhost:1234` with `qwen3-vl-4b-instruct` loaded
- Python packages (for token matching): `face_recognition` or `imagehash`

### What it does each run

1. Pre-flight checks LM Studio — skips batch if offline
2. Processes up to 10 unclassified images per run
3. Detects transparent PNGs as tokens; runs face-match via `06-match-token.py`
4. Calls Qwen3-VL with base64 image (max 1024px) → race, class, element, environment
5. Renames file to canonical slug: `{race}-{class}-{element}.{ext}`
6. Writes `01-Processing/{slug}.md` with full AGENTS.md frontmatter
7. Updates `state/processed-images.json` and `system/state/inbox-queue.json`

### State files

| File | Purpose |
|------|---------|
| `state/processed-images.json` | Classification results per image path |
| `state/token-links.json` | Face-match results: token → source portrait |
| `state/processed-images.txt` | Legacy plain-text skip list (migrated) |

### Force re-classify an image

Remove the image's entry from `state/processed-images.json`, then run the agent.

### Troubleshooting

| Symptom | Check |
|---------|-------|
| "LM Studio offline" in log | Start LM Studio, load `qwen3-vl-4b-instruct` |
| Image skipped silently | Already in `processed-images.json` with `status: ok` |
| Bad JSON from LLM | Check log for raw LLM response; usually retry fixes it |
| Token not linked to portrait | `face_recognition` not installed — fallback to `imagehash` |

---

## Lore Agent (NPC Generation)

**Purpose:** Generates PF2e NPC sheets from character images crossed with active campaign scenarios.

### Prerequisites

- **LM Studio** at `localhost:1234` with `qwen3-vl-4b-instruct`
- Vision agent must have run first (`processed-images.json` must exist with `status: ok` entries)

### What it does each run

1. Loads active scenarios from `state/scenarios.json`
2. Loads eligible images from vision's `processed-images.json` (portrait/body/token, status: ok)
3. Builds unprocessed `(image, scenario)` pairs
4. For each pair: calls Qwen3-VL with image + scenario context + up to 50 canon entities
5. Writes `01-Processing/{image-stem}-{scenario-id}.md` with full NPC frontmatter

### State files

| File | Purpose |
|------|---------|
| `state/processed-npcs.json` | Per `image|scenario` key → status, output path, NPC name |
| `state/scenarios.json` | Campaign scenario definitions (edit to add/remove scenarios) |

### Managing scenarios

Edit `state/scenarios.json` to activate or deactivate campaigns:

```json
{
  "scenarios": [
    {
      "id": "A1",
      "name": "Annûn",
      "description": "Shadow city port, political intrigue, pirate guilds, divine spirits",
      "active": true
    }
  ]
}
```

Set `"active": false` to stop generating NPCs for a scenario without deleting it.

### Force re-generate an NPC

Remove the `{relPath}|{scenarioId}` key from `state/processed-npcs.json`, then run the agent.

### Troubleshooting

| Symptom | Check |
|---------|-------|
| No NPCs generated | Vision agent run yet? Check `processed-images.json` |
| NPC has wrong stats | quality: 0 by design — human review required |
| LLM returns invalid JSON | Check log for raw response; 3 retries then marks as `error-llm` |

---

## Token Agent

**Purpose:** Generates circular 512×512 portrait tokens from classified character images. No LLM.

### Prerequisites

- Python packages: `Pillow`, `numpy`
- Optional (better face detection): `mtcnn` (primary, robust on stylized art), `opencv-python` (Haar fallback)
- **Moldura frame:** `00-Inbox/tokens/Molduras/moldura_default.png` must exist

### What it does each run

1. Reads vision's `processed-images.json` — filters to characters (not battlemaps/scenes), not already tokens
2. For each image: detects face → crops → applies circle mask → composites with moldura
3. Outputs `{source-stem}-token.png` alongside source image in `00-Inbox/images/`

### Config

Edit `state/10-generate-tokens.json`:

```json
{
  "output_size": 512,
  "padding": 0.2,
  "forehead_ratio": 0.3,
  "body_ratio": 0.3,
  "batch_size": 10,
  "moldura": "00-Inbox\\tokens\\Molduras\\moldura_default.png",
  "focus_head": [-20, 0, 0, 0]
}
```

`focus_head` is a CSS-like `[top, right, bottom, left]` offset in % of crop size. Negative top value moves crop upward (shows more forehead).

### Single-image mode

```powershell
python agents/token/tools/10-generate-tokens.py --source "00-Inbox\images\A1\human-warrior-fire.jpg" --vault-root "knowledge-base"
```

### Force regenerate

```powershell
python agents/token/tools/10-generate-tokens.py --force --vault-root "knowledge-base"
```

### Troubleshooting

| Symptom | Check |
|---------|-------|
| Token not generated | Image not in `processed-images.json` with `status: ok` |
| Face crop off-center | Adjust `focus_head` or `forehead_ratio` in config |
| Moldura not found | Check `state/10-generate-tokens.json` `moldura` path |
| Missing `mtcnn` | Falls back to OpenCV Haar (topmost), then upper-center crop |

---

## Wiki Agent

**Purpose:** Compiles raw `00-Inbox/` notes into structured entity drafts in `01-Processing/`.

### Prerequisites

- **LocalRouter** running at `localhost:8080`

### What it does each run

1. Pre-flight checks LocalRouter — aborts batch if offline (no permanent skip)
2. Loads up to 50 canon entities from `02-Library/` as context
3. Scans `00-Inbox/` for unprocessed `.md` files (not in `state/processed.txt`)
4. Strips HTML, truncates to 6000 chars
5. Calls LLM to produce AGENTS.md-compliant draft with Description/Details/Hooks/Related sections
6. Writes to `01-Processing/{slug}.md`

### State files

| File | Purpose |
|------|---------|
| `state/processed.txt` | Processed source file paths (one per line) |
| `state/bad-wiki-docs.txt` | Files that failed repeatedly (skip permanently) |

### Retry a failed document

Remove the path from `state/bad-wiki-docs.txt`, then run the agent.

### Troubleshooting

| Symptom | Check |
|---------|-------|
| "LocalRouter offline" | Start LocalRouter at :8080 |
| Draft has wrong entity type | Edit frontmatter manually; classification agent will not override |
| File stuck in processed.txt | Remove line from file to force reprocess |
| No wikilinks in draft | Canon `02-Library/` is empty — links injected from existing canon |

---

## Classification Agent

**Purpose:** Enriches `.md` frontmatter with tags, entity type, and duplicate flags. Runs on `00-Inbox/` and `01-Processing/`.

### Prerequisites

- **LocalRouter** running at `localhost:8080`

### What it does each run

1. Scans all `.md` files in `00-Inbox/` and `01-Processing/`
2. Skips files with >5 existing tags (already enriched) and files in `state/bad-docs.txt`
3. Calls LLM to assign 4–8 tags from the allowed 29-tag list
4. Calls LLM to infer entity type if missing
5. Checks slug against `02-Library/` filenames — injects `duplicate_of` warning if match found
6. Rewrites frontmatter in-place

### Allowed tags

`npc` · `creature` · `monster` · `location` · `dungeon` · `city` · `village` · `faction` · `quest` · `encounter` · `item` · `artifact` · `lore` · `religion` · `event` · `organization` · `timeline` · `undead` · `dark` · `fire` · `light` · `none` · `portrait` · `battlemap` · `scene` · `token` · `images` · `pathfinder2e`

### Allowed types

`npc` · `character` · `faction` · `location` · `city` · `village` · `dungeon` · `item` · `artifact` · `quest` · `encounter` · `creature` · `monster` · `event` · `religion` · `organization` · `timeline` · `lore`

### State files

| File | Purpose |
|------|---------|
| `state/bad-docs.txt` | Files that failed tag enrichment permanently |

### Retry a bad document

Remove path from `state/bad-docs.txt`, then run the agent.

### Troubleshooting

| Symptom | Check |
|---------|-------|
| File not getting tags | Already has >5 tags — threshold is 5 |
| Wrong type inferred | Edit frontmatter manually; agent skips files with existing type |
| duplicate_of injected incorrectly | Slug collision in `02-Library/` — rename one of the files |

---

## Review Agent

**Purpose:** Vault health monitor. Runs every 15 minutes. Produces JSON reports and dashboard data.

### What it does each run

1. Parses last 24h of `automation.log` — counts runs/errors/warnings per agent
2. Scans `01-Processing/` for:
   - **Pending review:** `reviewed: false` or `status: draft`
   - **Orphans:** no `[[wikilink]]` in content
   - **Quality score:** 0–10 computed per draft
3. Injects `suggestedQuality` into drafts that have `quality: 0`
4. Writes `state/reports/report-YYYY-MM-DD.json`
5. Rebuilds `state/reports/reports-data.js` (embeds all historical reports for dashboard)

### Quality scoring

| Criterion | Points |
|-----------|--------|
| Has `## Description` section | +2 |
| Has `relationships:` with at least one wikilink | +2 |
| Has 3 or more tags | +2 |
| Has `type:` field set | +2 |
| Has `source:` field set | +2 |

Score ≥ 7 = Library candidate. Score < 4 = reject.

### State files

| File | Purpose |
|------|---------|
| `state/reports/report-YYYY-MM-DD.json` | Daily health snapshot |
| `state/reports/reports-data.js` | Embedded report history for dashboard |

### Read latest report

```powershell
$report = Get-Content "agents/review/state/reports/report-$(Get-Date -Format 'yyyy-MM-dd').json" | ConvertFrom-Json
$report.vaultHealth.pendingReview | Select-Object file, suggestedQuality
```

### Troubleshooting

| Symptom | Check |
|---------|-------|
| Report not updating | Review agent interval is 900s (15 min) — may not have fired yet |
| All quality scores = 0 | `suggestedQuality` is computed suggestion only — `quality` field is human-set |
| Dashboard shows no data | `reports-data.js` rebuild failed — check log for write errors |

---

## Extending the System

### Create a new agent

```powershell
$name = "my-agent"
$vault = "knowledge-base"
$base = "$vault\agents\$name"
@("skills","prompts","tools","generated-tools","state","state\logs") | ForEach-Object {
  New-Item -ItemType Directory -Force "$base\$_"
}
```

Then:
1. Write `AGENT.md` (see schema in `README.md`)
2. Add to `registry.yaml`
3. Add to `runtime/state/agent.json` + `tasks-state.json`

### Override LLM endpoint

Edit `registry.yaml` `llm_endpoints` section. All agents that reference the alias pick up the change without script edits.

### Force-run a single agent

```powershell
pwsh agents/{agent}/tools/{tool-script}.ps1
```

Or update `runtime/state/tasks-state.json` to set `lastRun` to epoch time for that agent — runner will fire it on next tick.

### View logs

```powershell
# Master log (all agents)
Get-Content agents/runtime/state/logs/automation.log -Tail 50

# Single agent log
Get-Content "agents/vision/state/logs/06-classify-images_$(Get-Date -Format 'yyyy-MM-dd').log"
```
