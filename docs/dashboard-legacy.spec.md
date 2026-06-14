# Nexus Campaigns Dashboard — Product Specification

## 1. Purpose

Mission-control dashboard for the AI-powered Dungeon Master content pipeline.
Provides operational visibility, content quality control, human review workflows,
and knowledge-base analytics over an Obsidian vault.

---

## 2. Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Executive Dashboard | KPIs, pipeline summary, agent health, activity feed |
| `/pipeline` | Pipeline | Visual stage flow, folder ownership table |
| `/queue` | Queue Dashboard | inbox-queue.json state, stuck items, per-agent slots |
| `/review` | Human Review | 01-Processing/ drafts, quality scores, promotion workflow |
| `/agents` | Agent Monitoring | Per-agent health, runs/errors/schedule table, live log |
| `/library` | Library Analytics | 02-Library/ stats, type breakdown, quality histogram |
| `/errors` | Error Monitoring | Grouped agent errors from log tail + daily report |

---

## 3. Navigation

```
🐉 Nexus Campaigns
──────────────────────
OVERVIEW
  ⬡  Executive
  ⟶  Pipeline
──────────────────────
OPERATIONS
  🤖  Agents
  📥  Queue
  ⚡  Errors
──────────────────────
CONTENT
  👁  Review
  📚  Library
──────────────────────
● Live · 30s refresh
```

---

## 4. Information Architecture

### Executive Dashboard
Answers: "What is the current state of the entire factory in 30 seconds?"

KPI cards (row 1):
- Library Entities — total approved entities in 02-Library
- Pending Review — unreviewed drafts in 01-Processing
- Inbox Files — total files in 00-Inbox
- Processing — total drafts in 01-Processing
- Errors 24h — summed agent error count
- Stuck Items — queue items blocked > 2h

KPI cards (row 2):
- Images Classified + tokens generated
- NPCs Generated across scenarios
- Orphan Entities — no relationships
- Campaign Files

Panel row:
- Pipeline Flow — horizontal bar per stage with counts
- Queue Health — total/pending/done/stuck counts
- Last Report — 24h run summary

Agent Health grid: compact AgentCard per agent (status dot + stats + schedule)

Activity Feed: scrollable log tail with severity coloring

### Pipeline Page
- Stage count cards (inbox/processing/review/library/campaigns)
- Flow metrics (24h throughput, pending review, library size)
- Visual pipeline: vertical sequence of StepBox components with connectors
- Folder ownership table: folder → owner agent → file count → purpose

### Queue Page
- Summary: total/pending/done/stuck/byType
- Stuck items section (danger border, priority display)
- Pending items table
- Completed items table
- Per-item: path, type, age (color-coded), per-agent slot status badges

### Review Page
- Summary: total/needs-review/high-quality/orphans
- Review queue table sorted by: unreviewed first, then suggestedQuality desc
- Per-item: entity ID, type icon, description preview, status badge, quality bar
  (shows actual quality or ~suggested), tags, link count, source, created time
- Promotion workflow guide (5-step visual)

### Agent Monitoring Page
- 4 summary cards: total/healthy/errored/runs-24h
- Full AgentCard grid (detailed)
- Agent Schedule table: name/script/status/interval/lastRun/nextRun/runs/errors
- Live log feed (full)

### Library Analytics Page
- 4 KPIs: total/types/avgQuality/orphans
- Entity type breakdown (horizontal bar chart)
- Quality histogram (buckets 1-10, color-coded red/yellow/green)
- Recently added table: id/type/quality/tags/links/created

### Error Monitoring Page
- 3 summary cards: total errors in log tail / agents with errors / errors in last report
- 24h report breakdown table (per agent: runs/completed/errors/warnings/lastRun)
- Per-agent error groups: timestamp + message for each error
- Empty state when clean

---

## 5. Data Model (TypeScript)

### Core interfaces (src/lib/types.ts)

```typescript
AgentInfo {
  id, name, script, intervalSeconds, description
  lastRun, nextRun, status: 'idle'|'running'|'error'|'offline'
  runs24h, completedRuns24h, errors24h, warnings24h
  avgRunMs
}

QueueItem {
  path, ingestedAt, type: 'image'|'document'|'other'
  agents: Record<string, 'pending'|'done'|'skip'|'error'>
  ageMs, isStuck
}

ReviewItem {
  path, filename, id, type, status, quality, suggestedQuality
  tags, source, reviewed, relationships
  hasRelationships, isOrphan, createdAt, updatedAt, description
}

PipelineStage { id, name, folder, count, icon, color }
LogLine { timestamp, taskId, message, severity }
DailyReport { date, generatedAt, summary, tasks, vaultHealth }
VaultStats { folders, images, npcs, growth }
```

---

## 6. Database Design

**No database required.** All data read directly from vault filesystem:

| Source | Data |
|--------|------|
| `.system/inbox-queue.json` | Queue state |
| `.system/processed-images.json` | Vision agent results |
| `.system/processed-npcs.json` | Lore agent results |
| `.system/generated-tokens.json` | Token results |
| `.system/tasks.json` | Task config |
| `.system/tasks-state.json` | Last run times |
| `.system/logs/automation.log` | Combined log |
| `.system/reports/report-*.json` | Daily reports |
| `01-Processing/*.md` | Draft entities (parse frontmatter) |
| `02-Library/**/*.md` | Canon entities (parse frontmatter) |
| Folder file counts | Stage counts |

**Rationale:** the vault is the single source of truth. Adding a database would
create drift. Next.js server components + API routes read files directly at
request time. No sync daemon needed.

If growth requires caching: add an in-memory TTL cache (30s) in vault.ts.
For history/trends: write daily snapshots to `.system/snapshots/*.json`
from the Review Agent.

---

## 7. API Design

All routes use `force-dynamic` (no build-time caching).

| Method | Route | Returns |
|--------|-------|---------|
| GET | `/api/vault/stats` | VaultStats |
| GET | `/api/queue` | QueueStats |
| GET | `/api/agents` | AgentInfo[] |
| GET | `/api/review` | ReviewItem[] |
| GET | `/api/pipeline` | PipelineStats |
| GET | `/api/logs?limit&severity&task` | LogLine[] |
| GET | `/api/reports/latest` | DailyReport |

All JSON. No auth (local-only app). No WebSocket — pages use 30s meta-refresh
or client-side polling via SWR.

---

## 8. Frontend Stack

| Tool | Why |
|------|-----|
| **Next.js 15 App Router** | Server components read filesystem directly. No client-side CORS. SSR = zero loading flash. |
| **TypeScript** | Strict typing for vault data shapes. Catches path/field errors at compile time. |
| **Tailwind CSS** | Utility-first. Design tokens in config. Dark theme with CSS variables. |
| **IBM Plex Sans** | Operations-center aesthetic. Excellent tabular numerals. Free Google Font. |
| **Recharts** | (Future) growth trend charts. Composable React components. |
| **React Flow** | (Future) interactive knowledge graph. Node-edge layout built in. |
| **gray-matter** | Parse YAML frontmatter from vault markdown files. Zero config. |
| **date-fns** | Relative time, formatting. Tree-shakable. |
| **SWR** | (Future) client-side polling with stale-while-revalidate. |

---

## 9. Design System

Based on Dashboard skill design system:

**Colors (Tailwind tokens)**
```
surface DEFAULT: #09090b  — base background
surface-1: #111113        — card background
surface-2: #18181b        — hover states
surface-3: #27272a        — borders
surface-4: #3f3f46        — disabled/muted borders
primary:   #0C5CAB        — interactive blue
success:   #10b981        — approved/healthy/good
warning:   #f59e0b        — draft/pending/caution
danger:    #ef4444        — error/stuck/orphan
neutral:   #6b7280        — secondary text
```

**Status mapping**
- Agent idle → neutral dot
- Agent running → success dot (pulsing)
- Agent error → danger dot (pulsing)
- Queue pending → warning badge
- Queue done → success badge
- Queue stuck → danger badge
- Entity draft → warning badge
- Entity approved → success badge
- Quality 1-3 → danger
- Quality 4-6 → warning
- Quality 7-10 → success

**Typography**
- Body: IBM Plex Sans 14px/1.5
- Labels: 12px uppercase tracking-wider text-neutral
- KPI values: 24-32px font-semibold tabular-nums
- Code/paths: IBM Plex Mono

**Component library (custom)**
- KPICard — metric with label, value, trend, accent color
- AgentCard — status dot, stats grid, schedule footer
- ActivityFeed — log viewer with severity coloring
- PageHeader — icon + title + subtitle + action slot
- QualityBar — 0-10 bar with color zones
- StatusBadge — colored pill with border

---

## 10. Component Inventory

| Component | Purpose | Data Source |
|-----------|---------|-------------|
| `KPICard` | Single metric display | Any count |
| `AgentCard` | Agent health snapshot | `/api/agents` |
| `ActivityFeed` | Scrollable log viewer | `/api/logs` |
| `PageHeader` | Consistent page header | Props |
| `Sidebar` | Navigation | Static + pathname |
| `PipelineBar` | Horizontal stage count bars | Pipeline stats |
| `QueueTable` | Queue item rows with slot badges | `/api/queue` |
| `QualityBar` | 0-10 horizontal bar | ReviewItem.quality |
| `QualityHistogram` | 10-bucket bar chart | Library data |
| `StepBox` | Single pipeline step card | Static |
| `SumCard` | Compact count card | Page-level aggregate |
| `QueueRow` | Label+value row in summary | Page-level |
| `Metric` | Centered metric block | Page-level |

---

## 11. Real-Time Strategy

Pages use Next.js `force-dynamic` — every request reads fresh data.
Sidebar shows "Live · 30s refresh" indicator.

For live updates, add to any client page:
```typescript
'use client'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'
useEffect(() => {
  const t = setInterval(() => router.refresh(), 30_000)
  return () => clearInterval(t)
}, [router])
```

Future WebSocket: add `wss://` endpoint in Next.js Route Handler using
`chokidar` to watch `.system/*.json` and push change events to clients.

---

## 12. MVP Scope (Implemented)

- [x] Project scaffold (Next.js 15, TypeScript, Tailwind)
- [x] Design system (tokens, components, dark theme, IBM Plex Sans)
- [x] Sidebar navigation (7 sections)
- [x] Executive Dashboard (KPIs, pipeline bar, queue health, agent grid, activity feed)
- [x] Pipeline page (stage counts, visual flow, folder ownership)
- [x] Queue page (full queue table, stuck/pending/done groups)
- [x] Review page (draft table, quality bars, promotion guide)
- [x] Agent Monitoring page (cards, schedule table, live log)
- [x] Library Analytics page (type breakdown, quality histogram, recent additions)
- [x] Error Monitoring page (grouped errors, 24h report breakdown)
- [x] All 7 API routes (vault stats, queue, agents, review, pipeline, logs, latest report)
- [x] Vault reader (filesystem, frontmatter, log parser)

---

## 13. Future Expansion

### Phase 2
- [ ] Client-side 30s auto-refresh (useEffect + router.refresh)
- [ ] Campaign Dashboard (`/campaigns`) — reads 03-Campaigns/
- [ ] Knowledge Graph (`/graph`) — React Flow + 02-Library relationship data
- [ ] Search across all entities
- [ ] Inline review actions (approve/reject via API writing to vault files)

### Phase 3
- [ ] WebSocket live updates via chokidar file watcher
- [ ] Growth trend charts (Recharts LineChart, snapshots over time)
- [ ] Notifications (browser Notification API for new errors or stuck items)
- [ ] Scenario management UI (edit scenarios.json)
- [ ] Token gallery (browse 05-Assets/tokens/)

### Phase 4
- [ ] Auth (local Passkey or API key, for shared team use)
- [ ] Bulk operations (approve all high-quality drafts)
- [ ] Export to PDF/HTML for session prep
- [ ] Campaign session notes integration

---

## 14. Running

```bash
cd .system/dashboard
npm install
npm run dev         # http://localhost:3131
```

Requires: Node.js 18+, vault at `knowledge-base`.
Override vault path: edit `.env.local` → `VAULT_ROOT=<path>`.
