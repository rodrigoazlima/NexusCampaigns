# DM Knowledge Factory — Dashboard Product Specification

**Version:** 1.0
**Date:** 2026-06-13
**Supersedes:** `docs/dashboard-legacy.spec.md`
**Implementation:** See `docs/admin-dashboard.spec.md`

---

## 1. Purpose

Mission-control dashboard for the AI-powered Dungeon Master content pipeline.
Provides operational visibility, content quality control, human review workflows,
and knowledge-base analytics over an Obsidian vault.

**Audience:** DM (human operator) running the local pipeline.
**Location:** `dashboard/` · **URL:** http://localhost:3131

---

## 2. Pages

| Route | Page | One-liner |
|-------|------|-----------|
| `/` | Executive Dashboard | Factory state in 30 seconds |
| `/pipeline` | Pipeline | Stage flow, counts, folder ownership |
| `/queue` | Queue | inbox-queue state, stuck items |
| `/review` | Human Review | 01-Processing drafts, promotion workflow |
| `/agents` | Agent Monitoring | Per-agent health, schedule, live log |
| `/library` | Library Analytics | 02-Library stats, type breakdown, quality |
| `/errors` | Error Monitoring | Grouped errors from log + daily report |

---

## 3. Navigation

```
🐉 Knowledge Factory
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

### Executive Dashboard `/`

Answers: "What is the current state of the entire factory?"

**KPI row 1:** Library Entities · Pending Review · Inbox Files · Processing · Errors 24h · Stuck Items

**KPI row 2:** Images Classified · Tokens Generated · NPCs Generated · Orphan Entities · Campaign Files

**Panel row:**
- Pipeline Flow — horizontal bar per stage with file counts
- Queue Health — total / pending / done / stuck
- Last Report — 24h agent run summary

**Agent Health grid:** compact `AgentCard` per agent (status dot + stats + schedule)

**Activity Feed:** scrollable log tail, severity-colored

---

### Pipeline Page `/pipeline`

- Stage count cards: inbox → processing → review → library → campaigns
- Flow metrics: 24h throughput, pending review, library size
- Visual pipeline: vertical `StepBox` sequence with connectors
- Folder ownership table: folder → owner agent → file count → purpose

---

### Queue Page `/queue`

- Summary: total / pending / done / stuck / by-type breakdown
- Stuck items (danger border, > 2h threshold)
- Pending items table
- Completed items table
- Per-item columns: path · type · age (color-coded) · per-agent slot badges

---

### Human Review Page `/review`

- Summary: total drafts / needs-review / high-quality / orphans
- Review table sorted: unreviewed first, then suggestedQuality desc
- Per-row: entity id · type icon · description preview · status badge · quality bar · tags · link count · source · created
- 5-step promotion workflow guide (sidebar or footer panel)

---

### Agent Monitoring Page `/agents`

- 4 summary KPIs: total · healthy · errored · runs-24h
- `AgentCard` grid (full detail mode)
- Agent Schedule table: name / status / interval / lastRun / nextRun / runs / errors
- Live log feed (full, filterable by severity and task)

---

### Library Analytics Page `/library`

- 4 KPIs: total entities · distinct types · avg quality · orphan count
- Entity type breakdown — horizontal bar chart
- Quality histogram — 10 buckets (1–10), color-coded red / yellow / green
- Recently added table: id · type · quality · tags · links · created

---

### Error Monitoring Page `/errors`

- 3 summary cards: errors in log tail · agents with errors · errors in last report
- 24h report breakdown table: per-agent runs / completed / errors / warnings / lastRun
- Per-agent error groups: timestamp + message per error
- Empty state when clean

---

## 5. Design System

### Colors (Tailwind tokens)

```
surface:   #09090b   — base background
surface-1: #111113   — card background
surface-2: #18181b   — hover states
surface-3: #27272a   — borders
surface-4: #3f3f46   — disabled / muted borders
primary:   #0C5CAB   — interactive blue
success:   #10b981   — approved / healthy / good
warning:   #f59e0b   — draft / pending / caution
danger:    #ef4444   — error / stuck / orphan
neutral:   #6b7280   — secondary text
```

### Status Mapping

| State | Color |
|-------|-------|
| Agent idle | neutral dot |
| Agent running | success dot (pulse) |
| Agent error | danger dot (pulse) |
| Queue pending | warning badge |
| Queue done | success badge |
| Queue stuck | danger badge |
| Entity draft | warning badge |
| Entity approved | success badge |
| Quality 1–3 | danger |
| Quality 4–6 | warning |
| Quality 7–10 | success |

### Typography

| Use | Style |
|-----|-------|
| Body | IBM Plex Sans 14px / 1.5 |
| Labels | 12px uppercase tracking-wider text-neutral |
| KPI values | 24–32px font-semibold tabular-nums |
| Paths / code | IBM Plex Mono |

---

## 6. Component Inventory

| Component | Purpose | Data Source |
|-----------|---------|-------------|
| `KPICard` | Single metric with label + accent | Any count |
| `AgentCard` | Status dot, stats grid, schedule | `/api/agents` |
| `ActivityFeed` | Scrollable log with severity colors | `/api/logs` |
| `PageHeader` | Icon + title + subtitle + action slot | Props |
| `Sidebar` | 7-section nav + live indicator | Static + pathname |
| `PipelineBar` | Horizontal stage count bars | Pipeline stats |
| `QueueTable` | Queue rows with per-agent slot badges | `/api/queue` |
| `QualityBar` | 0–10 horizontal bar, color-zoned | `ReviewItem.quality` |
| `QualityHistogram` | 10-bucket bar chart | Library data |
| `StepBox` | Single pipeline step card | Static |
| `StatusBadge` | Colored pill with border | Props |
| `SumCard` | Compact labeled count | Page-level aggregate |

---

## 7. Real-Time Strategy

Pages use Next.js `force-dynamic` — every request reads fresh vault data.
Sidebar shows "Live · 30s refresh" indicator.

**Current:** meta-refresh or client `useEffect` + `router.refresh()` every 30s.

**Future:** WebSocket via Next.js Route Handler + `chokidar` watching `.agents/runtime/state/*.json`, pushing change events to clients.

---

## 8. Implementation Phases

### Phase 1 — MVP (complete)

- [x] Next.js 15 App Router scaffold (TypeScript, Tailwind, IBM Plex Sans)
- [x] Design system tokens + dark theme
- [x] Sidebar navigation (7 sections)
- [x] All 7 pages (Executive, Pipeline, Queue, Review, Agents, Library, Errors)
- [x] All 7 API routes
- [x] Vault filesystem reader + frontmatter parser + log parser

### Phase 2 — Automation & Analytics

- [ ] Client-side 30s auto-refresh (`AutoRefresh` component)
- [ ] Campaign Dashboard `/campaigns` — reads `03-Campaigns/`
- [ ] Knowledge Graph `/graph` — React Flow + `02-Library/` relationship data
- [ ] Full-text search across all entities
- [ ] Inline review actions (approve/reject via API writing vault frontmatter)

### Phase 3 — Live & Rich

- [ ] WebSocket live updates via `chokidar` file watcher
- [ ] Growth trend charts — Recharts LineChart, daily snapshot series
- [ ] Browser notifications for new errors or stuck items
- [ ] Scenario management UI (edit `scenarios.json`)
- [ ] Token gallery (`05-Assets/tokens/`)

### Phase 4 — Team & Export

- [ ] Auth (local Passkey or API key)
- [ ] Bulk approve (all drafts with quality ≥ 7)
- [ ] Export to PDF / HTML for session prep
- [ ] Campaign session notes integration

---

## 9. Running

```bash
cd dashboard
npm install
npm run dev   # http://localhost:3131
```

Requires Node.js 18+. Override vault path: set `VAULT_ROOT` in `dashboard/.env.local`.
