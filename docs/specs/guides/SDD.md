# Software Design Document — Pathway Nexus Campaigns

**Version:** 1.3  
**Date:** 2026-06-10  
**Vault Root:** `knowledge-base/`

---

## Purpose

Automated pipeline that transforms raw campaign inspiration (images, documents, notes) into reusable, linked, quality-gated knowledge assets for Dungeon Masters.

Audience: contributors, automation developers, Claude Code agents.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Windows Service (NSSM)                       │
│  daemon → runtime/runner (every 60s)                                │
│         ↓                                                           │
│   agent.json discovery + tasks-state.json → dispatch Claude agents  │
└─────────────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         Agent Pipeline                              │
│                                                                     │
│  00-Inbox/  →  [Ingestion] → inbox-queue.json                       │
│                    ↓                                                │
│             [Vision Agent] → 01-Processing/ drafts                  │
│                    ↓                                                │
│             [Lore Agent]   → NPC sheets (01-Processing/)            │
│                    ↓                                                │
│             [Token Agent]  → circular tokens (00-Inbox/images/)     │
│                    ↓                                                │
│             [Classification Agent] → enriched frontmatter           │
│                    ↓                                                │
│             (human review — sets status: approved, quality: N)      │
│                    ↓                                                │
│               02-Library/ (canon)                                   │
│                    ↓                                                │
│             [Wikilink Agent] → [[links]] in 02-Library/             │
│             [Wiki Agent]     → 03-Campaigns/, 04-Relationships/     │
└─────────────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      Health & Observability                         │
│  [Review Agent]  → agents/review/state/reports/report-YYYY-MM-DD.json │
│  [Repair Agent]  → agents/review/state/reports/repair-YYYY-MM-DD.json │
│  [Cleanup Agent] → purge logs/reports older than cleanupDays        │
│  agents/runtime/state/agent-metrics.json → per-agent run history   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent Definitions

Agents are defined by their **actions** — discrete, named operations each agent may perform. Implementation language and script names are out of scope for this document.

### Ingestion

**Trigger:** hourly | **Reads:** `00-Inbox/` | **Writes:** `inbox-queue.json`

| Action | Description |
|--------|-------------|
| `CleanFilenames` | Strip non-ASCII / emoji chars from filenames in `00-Inbox/`. Idempotent. |
| `ConvertDocx` | Convert `.docx` files to GFM Markdown. Extract embedded images to `00-Inbox/images/{slug}/`. |
| `ScanInbox` | Discover all files in `00-Inbox/` not yet registered. |
| `RegisterQueue` | Add new files to `inbox-queue.json` with type classification and agent slots. |

---

### Vision

**Trigger:** hourly | **Reads:** `00-Inbox/images/`, `processed-images.json` | **Writes:** `01-Processing/*.md`, `agents/vision/state/processed-images.json`

| Action | Description |
|--------|-------------|
| `DetectToken` | Identify PNG images as tokens by transparent corner/edge pixels. |
| `MatchTokenFace` | Match token image to a source character image via face distance scoring. |
| `ClassifyImage` | Call vision LLM to produce type / race / class / element / environment classification. |
| `RenameToSlug` | Rename image file to canonical slug format. Bump filename on collision. |
| `WriteDraft` | Write AGENTS.md-compliant image metadata draft to `01-Processing/`. |
| `UpdateJsonIndex` | Update entry in `agents/vision/state/processed-images.json`. |
| `MarkQueueDone` | Set `agents.vision = done` in `inbox-queue.json`. |

---

### Lore

**Trigger:** hourly | **Reads:** `processed-images.json`, `scenarios.json`, `02-Library/` | **Writes:** `01-Processing/{slug}-A{arc}.md`, `processed-npcs.json`

| Action | Description |
|--------|-------------|
| `LoadCanonContext` | Load approved entities from `02-Library/` (id, type, tags, relationships). |
| `GenerateNPC` | Call vision LLM with image + scenario pair to produce a full NPC sheet. |
| `WriteDraft` | Write AGENTS.md-compliant NPC markdown to `01-Processing/`. |
| `MarkQueueDone` | Set `agents.lore = done` in `inbox-queue.json`. |

---

### Token

**Trigger:** hourly | **Reads:** `processed-images.json`, moldura frame | **Writes:** `*-token.png` in `00-Inbox/images/`, `generated-tokens.json`

| Action | Description |
|--------|-------------|
| `DetectFace` | Locate face bounding box in portrait image (mediapipe or Haar cascade). |
| `CropToCircle` | Face-aware square crop + anti-aliased circular mask (4× supersampled). |
| `CompositeMoldura` | Overlay cropped circle onto moldura frame image. |
| `SaveToken` | Write token PNG alongside source image. Record in `generated-tokens.json`. |

---

### Classification

**Trigger:** hourly | **Reads:** `00-Inbox/`, `01-Processing/`, `02-Library/` | **Writes:** enriched frontmatter in-place

| Action | Description |
|--------|-------------|
| `EnrichTags` | Call LLM to suggest DM-domain tags for notes with ≤5 tags. |
| `InferType` | Call LLM to assign `type:` field when missing. |
| `FlagDuplicates` | Compare slug against `02-Library/` entries; warn on similarity. |

---

### Wiki

**Trigger:** hourly | **Reads:** `00-Inbox/` markdown, `02-Library/` | **Writes:** `01-Processing/` entity pages

| Action | Description |
|--------|-------------|
| `LoadCanonContext` | Load `02-Library/` entities as LLM context. |
| `SynthesizeEntity` | Call LLM to produce a structured entity page from raw inbox notes. |
| `WriteDraft` | Write synthesized page to `01-Processing/`. |

---

### Wikilink

**Trigger:** hourly | **Reads:** `02-Library/**/*.md` | **Writes:** `## Related` sections in `02-Library/`

| Action | Description |
|--------|-------------|
| `ScoreEntityPairs` | Score note pairs by shared tags, slug mentions, and body keyword overlap. |
| `InsertWikilinks` | Inject `[[wikilink]]` lines into `## Related` section (create section if absent). |

---

### Review

**Trigger:** every 15 min | **Reads:** `01-Processing/`, `02-Library/`, `inbox-queue.json`, `automation.log` | **Writes:** `reports/report-YYYY-MM-DD.json`

| Action | Description |
|--------|-------------|
| `ListPendingReview` | Collect drafts where `reviewed: false`. |
| `DetectOrphans` | Find entities with empty `relationships`. |
| `ScoreQuality` | Compute completeness score (0–10) per draft. |
| `SummarizeLogs` | Extract errors and warnings per agent from last 24h of `automation.log`. |
| `WriteReport` | Emit structured JSON report. |
| `ScanShortFiles` | Find `01-Processing/` files with fewer than 10 body lines. |
| `FlagReprocessing` | Set `needs_reprocessing: true` in frontmatter of short files. |

---

### Repair

**Trigger:** every 15 min | **Reads:** `automation.log`, `tasks-state.json`, `runner.lock`, `agent-metrics.json` | **Writes:** `reports/repair-YYYY-MM-DD.json`

| Action | Description |
|--------|-------------|
| `ParseErrorPatterns` | Scan `automation.log` for stale-lock, missing-directory, and missing-image-ref patterns. |
| `RemoveStaleLock` | Delete `runner.lock` if older than 30 minutes. |
| `CreateMissingDirs` | Create any missing `system/` subdirectories. |
| `ValidateImageRefs` | Verify image references in `processed-images.json` using SHA256 identity. |
| `DetectOverdueAgents` | Flag any agent not run within `2 × intervalSeconds`. |

---

### Cleanup

**Trigger:** daily | **Reads:** `system/logs/`, `system/reports/`, `agent-metrics.json` | **Writes:** purges old files, trims metrics

| Action | Description |
|--------|-------------|
| `PurgeLogs` | Delete log files older than `cleanupDays`. |
| `PurgeReports` | Delete report files older than `cleanupDays`. |
| `TrimMetrics` | Trim `agent-metrics.json` run history to last 100 entries per agent. |

---

## Spec Index

### Topics

| Topic | Spec |
|-------|------|
| Automation system (process model, task config, metrics, adding agents) | [automation-system.spec.md](specs/automation-system.spec.md) |
| Agent dispatch (agent.json schema, dispatch types, shared runners, auth) | [agent-dispatch.spec.md](specs/agent-dispatch.spec.md) |
| Agent registry (registry.yaml schema, active/planned agents, LLM endpoints) | [agent-registry.spec.md](specs/agent-registry.spec.md) |
| Data contracts (frontmatter, naming, logging, encoding) | [data-contracts.spec.md](specs/data-contracts.spec.md) |
| State files (all JSON/text state file schemas and locations) | [state-files.spec.md](specs/state-files.spec.md) |
| Shared Python library (agents/shared/ modules and interfaces) | [shared-library.spec.md](specs/shared-library.spec.md) |
| LLM integration (providers, model assignments, call parameters) | [llm-integration.spec.md](specs/llm-integration.spec.md) |
| Linking rules (required links, wikilink syntax) | [linking-rules.spec.md](specs/linking-rules.spec.md) |
| Security constraints (quality gate, human-only fields, API keys) | [security.spec.md](specs/security.spec.md) |
| Service installation and uninstallation (Windows, Linux, macOS) | [service-install.spec.md](specs/service-install.spec.md) |

---

## Open Design Items

| # | Item | Status |
|---|------|--------|
| 1 | Wiki Agent cross-link generation for `04-Relationships/` — implementation scope partial | Open |
| 2 | Classification/Wiki Agent use LocalRouter port 8080 — these are configured in `registry.yaml` `llm_endpoints`; `agent.json` dispatch still references legacy path | Partially Resolved |
| 3 | Face matching — no formal spec for distance threshold or match method | Open |
| 4 | Dashboard API (`/review/<sha256>` routes) — not documented | Open |
| 5 | `scenarios.json` schema — now documented in [state-files.spec.md](specs/state-files.spec.md); default scenario in `agents/lore/state/scenarios.json` | Resolved |
| 7 | Planned agents (canon, relationship, deduplication, curator, search, adventure-builder, session-builder, encounter-builder) — all `status: planned` in registry.yaml | Tracking |
