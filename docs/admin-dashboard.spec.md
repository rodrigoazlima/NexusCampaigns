# Admin Dashboard — Implementation Spec

**Version:** 2.1  
**Date:** 2026-06-13  
**Supersedes:** `.system/dashboard-legacy/SPEC.md` (stale paths)  
**Augments:** `docs/dashboard.SPEC.md` (product spec, still valid for pages/components/design)

---

## Purpose

Next.js dashboard for the Nexus Campaigns. Reads live vault and agent state from the filesystem. No database — vault is the single source of truth.

**Location:** `dashboard/` (project root)  
**Run:** `cd dashboard && npm run dev` → http://localhost:3131

---

## Tech Stack

| Tool | Version | Role |
|------|---------|------|
| Next.js | 16 App Router | SSR, API routes, `force-dynamic` |
| TypeScript | 5 | Type safety for vault data shapes |
| Tailwind CSS | 3 | Design tokens, dark theme |
| IBM Plex Sans / Mono | — | Operations-center typography |
| gray-matter | 4 | Parse YAML frontmatter from vault .md files |
| yaml | 2 | Parse registry.yaml for agent config |
| date-fns | 4 | Relative time, formatting |
| lucide-react | — | Icons |
| Recharts | 2 | Charts (quality histogram, trends) |
| ReactFlow | 11 | Knowledge graph (Phase 2) |
| SWR | 2 | Client-side polling (Phase 2) |

---

## State File Paths (authoritative)

All paths relative to `PROJECT_ROOT` (`C:\opt\GitHub\NexusCampaigns`).

| Data | Actual Path |
|------|-------------|
| Agent registry | `.agents/registry.yaml` |
| Agent last-run times | `.agents/runtime/state/tasks-state.json` |
| Agent run metrics | `.agents/runtime/state/agent-metrics.json` |
| Inbox queue | `.shared/state/inbox-queue.json` |
| Automation log | `.agents/runtime/state/logs/automation.log` |
| Daily reports | `.agents/review/state/reports/report-YYYY-MM-DD.json` |
| Repair reports | `.agents/review/state/reports/repair-YYYY-MM-DD.json` |
| Processed images | `.agents/vision/state/processed-images.json` |
| Processed NPCs | `.agents/lore/state/processed-npcs.json` |
| Generated tokens | `.agents/token/state/generated-tokens.json` |
| Vault markdown | `knowledge-base/{00-Inbox,01-Processing,02-Library,...}/**/*.md` |

`VAULT_ROOT` = `knowledge-base/` (absolute: `C:\opt\GitHub\NexusCampaigns\knowledge-base`)

---

## Environment Variables

`dashboard/.env.local`:
```
VAULT_ROOT=C:\opt\GitHub\NexusCampaigns\knowledge-base
PROJECT_ROOT=C:\opt\GitHub\NexusCampaigns
ANTHROPIC_API_KEY=           # required for /gm/chat agent chat feature
```

---

## vault.ts Path Constants

```typescript
export const VAULT_ROOT  = process.env.VAULT_ROOT  ?? 'C:\\opt\\GitHub\\NexusCampaigns\\knowledge-base'
const PROJECT_ROOT       = process.env.PROJECT_ROOT ?? path.resolve(process.cwd(), '..')
const STATE_DIR          = path.join(PROJECT_ROOT, '.agents', 'runtime', 'state')
const SHARED_DIR         = path.join(PROJECT_ROOT, '.shared', 'state')
const REPORTS_DIR        = path.join(PROJECT_ROOT, '.agents', 'review', 'state', 'reports')
const LOGS_DIR           = path.join(PROJECT_ROOT, '.agents', 'runtime', 'state', 'logs')
const VISION_STATE_DIR   = path.join(PROJECT_ROOT, '.agents', 'vision', 'state')
const LORE_STATE_DIR     = path.join(PROJECT_ROOT, '.agents', 'lore', 'state')
const TOKEN_STATE_DIR    = path.join(PROJECT_ROOT, '.agents', 'token', 'state')
```

`readJson()` takes absolute paths (not AUTO_DIR-relative strings).

---

## Agent Config Source: registry.yaml

`readTasks()` reads `.agents/registry.yaml` (YAML, not `tasks.json`).

Registry schema (relevant fields):
```yaml
agents:
  <name>:
    status: active | planned
    task_id: <string>           # key in tasks-state.json
    interval_seconds: <number>
    description: <string>
    llm: <endpoint-name> | none
```

Active agents (11): runtime, repair, ingestion, vision, lore, token, wiki, classification, review, wikilink, cleanup

Planned agents (7): relationship, deduplication, canon, curator, search, adventure-builder, session-builder

---

## Pages & Data Sources

### Read-only monitoring

| Route | Page | Key Data Sources |
|-------|------|-----------------|
| `/` | Executive Dashboard | vault folder counts, inbox-queue.json, agent-metrics.json, logs tail, reports |
| `/pipeline` | Pipeline | vault folder counts, processed-images.json, 01-Processing/ frontmatter |
| `/queue` | Queue | inbox-queue.json |
| `/review` | Human Review | 01-Processing/*.md frontmatter |
| `/agents` | Agent Monitoring | registry.yaml, tasks-state.json, agent-metrics.json, automation.log |
| `/library` | Library Analytics | 02-Library/**/*.md frontmatter |
| `/errors` | Error Monitoring | automation.log, reports/report-*.json |

### Game Master write interface

| Route | Page | Key Data Sources |
|-------|------|-----------------|
| `/gm` | GM Hub | 01-Processing/ counts, recent log events |
| `/gm/review` | GM Review | 01-Processing/*.md frontmatter (read+write) |
| `/gm/inbox` | GM Inbox | 00-Inbox/images/, inbox-queue.json |
| `/gm/tokens` | GM Tokens | 05-Assets/tokens/, 00-Inbox/images/, 00-Inbox/tokens/ |
| `/gm/chat` | Agent Chat | .agents/{name}/prompts/system.md, Anthropic API |

---

## API Routes

All use `export const dynamic = 'force-dynamic'`.

### Read-only

| Method | Route | Returns |
|--------|-------|---------|
| GET | `/api/vault/stats` | VaultStats |
| GET | `/api/queue` | QueueStats |
| GET | `/api/agents` | AgentInfo[] |
| GET | `/api/review` | ReviewItem[] |
| GET | `/api/pipeline` | PipelineStats |
| GET | `/api/logs?limit&severity&task` | LogLine[] |
| GET | `/api/reports/latest` | DailyReport |
| GET | `/api/reports/all` | Record<string, DailyReport> |
| GET | `/api/image?path=` | Binary image (serves vault PNG/JPG) |

### GM write interface

| Method | Route | Body | Action |
|--------|-------|------|--------|
| GET | `/api/gm/inbox` | — | InboxImage[] |
| GET | `/api/gm/tokens` | — | TokenFile[] |
| POST | `/api/gm/approve` | `{filename, quality}` | Merge frontmatter, copy to 02-Library/ |
| POST | `/api/gm/reject` | `{filename}` | Set status:rejected, quality:1 |
| POST | `/api/gm/flag` | `{filename}` | Set needs_reprocessing:true |
| POST | `/api/gm/edit` | `{filename, fields}` | Merge arbitrary frontmatter fields |
| POST | `/api/gm/chat` | `{message, agent, context}` | Call Anthropic API, return assistant reply |

---

## Components

### Shared widgets

| Component | File | Purpose |
|-----------|------|---------|
| `KPICard` | `components/widgets/KPICard.tsx` | Single metric with label + accent |
| `AgentCard` | `components/widgets/AgentCard.tsx` | Agent status dot + run stats |
| `ActivityFeed` | `components/widgets/ActivityFeed.tsx` | Log viewer with severity coloring |
| `PageHeader` | `components/widgets/PageHeader.tsx` | Icon + title + subtitle |
| `Sidebar` | `components/layout/Sidebar.tsx` | Nav (GM + monitoring sections) + live indicator |
| `AutoRefresh` | `components/AutoRefresh.tsx` | 30s client-side refresh |

### GM components

| Component | File | Purpose |
|-----------|------|---------|
| `ImageModal` | `components/gm/ImageModal.tsx` | Full-screen image overlay |
| `QualityPicker` | `components/gm/QualityPicker.tsx` | 1–10 button grid, color-zoned |
| `GMActionBar` | `components/gm/GMActionBar.tsx` | Approve / Reject / Flag / Edit buttons |
| `InboxImageCard` | `components/gm/InboxImageCard.tsx` | Thumbnail + agent slot badges + queue age |
| `TokenCard` | `components/gm/TokenCard.tsx` | Token PNG + frame switcher |
| `ReviewCard` | `components/gm/ReviewCard.tsx` | Draft card with image, actions, frontmatter |
| `ChatMessage` | `components/gm/ChatMessage.tsx` | Chat bubble with role styling |

---

## Design System

See `docs/dashboard.SPEC.md` § 9 for full token definitions. Summary:

```
surface:   #09090b    surface-1: #111113    surface-3: #27272a
primary:   #0C5CAB    success:   #10b981    warning:   #f59e0b    danger: #ef4444
```

Status colors: idle→neutral, running→success (pulse), error→danger (pulse)  
Quality: 1-3→danger, 4-6→warning, 7-10→success

---

## Phase 3 Backlog

- [ ] Client-side 30s auto-refresh via `AutoRefresh` component (already built)
- [ ] Knowledge Graph `/graph` — ReactFlow, 02-Library relationship edges
- [ ] Growth trend charts — Recharts LineChart, daily snapshot data
- [ ] Campaign Dashboard `/campaigns` — 03-Campaigns/ content
- [ ] Bulk approve (all drafts with quality ≥ 7 in one click)
- [ ] WebSocket live updates via `chokidar` file watcher
