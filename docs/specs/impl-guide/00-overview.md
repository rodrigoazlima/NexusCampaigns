# Agentic Evolution Plan — Overview

**Source:** `docs/agentic-review.md` + Claude-generated analysis (2026-06-10)  
**Scope:** Transform NexusCampaigns from a scheduled batch pipeline into a self-improving, semi-autonomous Nexus Campaigns.

---

## Current State (Level 3)

Nine active agents run on cron-like intervals. Each is a stateless processor: scan inbox → call LLM → write file → update state JSON. No agent observes its own output quality, no agent communicates with another at runtime, and the highest-value pipeline stages (Curator, Adventure-Builder, Session-Builder) are unimplemented stubs.

The infrastructure is production-grade. The reasoning layer is missing.

---

## Target State (Level 4)

```
00-Inbox  ──►  Ingestion  ──►  Vision  ──signal──►  Lore
                                                       │
                                                  [reflexion]
                                                       │
                                                  Curator
                                                       │
                                              02-Library (canon)
                                                       │
                              ┌────────────────────────┤
                              ▼                        ▼
                       Relationship              Canon Validator
                       Adventure-Builder
                              │
                       Session-Builder
```

Key differences from current state:
- Agents close feedback loops (generate → score → revise → write)
- Vision classification triggers Lore immediately via signal bus (no 1h wait)
- Curator performs semi-automated promotion to `02-Library/` — human approves with one field edit
- Adventure-Builder synthesises canon into playable arc outlines
- Cost is tracked per-task, per-run

---

## Implementation Phases

| Phase | Items | Target |
|-------|-------|--------|
| **P1 — Reasoning** | Reflexion loop (lore), cost tracking | Week 1–2 |
| **P2 — Automation** | Curator agent, canon validator | Week 3–4 |
| **P3 — Connectivity** | Signal bus, semi-automated promotion | Week 5–6 |
| **P4 — Synthesis** | Adventure-builder, session-builder | Month 2–3 |
| **P5 — Intelligence** | Semantic quality scoring, dedup | Month 3–4 |

---

## Guardrails — Non-Negotiable

These rules constrain every item in this plan. No recommendation may override them.

### G1 — Canon is immutable to agents

Agents may NEVER write to `02-Library/` with `status: approved`. The VaultGuard (`shared/vault_guard.py`) enforces this at code level. The Curator is the only exception: it writes `status: review`, NOT `status: approved`. Human sets `reviewed: true` and `status: approved`.

### G2 — Inbox is read-only

No agent may delete, rename, or overwrite files in `00-Inbox/`. The Ingestion Agent is the sole exception for emoji-cleanup renames and only within `00-Inbox/` per its AGENT.md spec.

### G3 — No self-approval

No agent may set `reviewed: true` in frontmatter. This field is human-only. Quality scoring by agents is advisory only.

### G4 — Reflexion loop caps

Any agent implementing self-critique must cap revision rounds at 2. Round 3 writes the best available output with a `needs_human_review: true` flag and stops. No infinite retry loops.

### G5 — Signal bus is fire-and-forget

Signals emitted by agents are advisory. The runtime decides whether to act on them. An agent emitting a signal has no guarantee the dependent agent runs. Agents must not depend on signal delivery for correctness.

### G6 — Cost tracking before semantic LLM judge

The semantic quality judge (P5) uses additional LLM tokens. It MUST NOT be enabled until per-task cost tracking (P1) is in place. Gate: `budget_usd_per_day` field in `agent.json` dispatch config must be set.

### G7 — Agent.json is the only config

No hardcoded task IDs, intervals, or model names in Python code. All dispatch configuration lives in `agent.json`. The runner discovers agents dynamically.

### G8 — Atomic writes everywhere

All file writes use `tmp → replace` pattern (see `shared/state_store.py`). No partial writes. This applies to new agents, new state files, and new report files.

### G9 — Interfaces before implementation

Every new agent capability requires an `I*` interface added to `shared/interfaces.py` before the implementation is written. Contracts first.

---

## Cross-Cutting Concerns

### Observability
- Every agent emits `--- START ---` and `--- DONE --- processed=N failed=N elapsed=Xs` log lines via `shared/logger.py`.
- New agents must follow the same pattern.
- Metrics are recorded to `agent-metrics.json` by the runner — no custom metrics code inside agents.

### Testing
- Every new tool function requires a unit test in `.agents/tests/`.
- Tests must use `conftest.py` fixtures and match existing test conventions.
- Integration tests may use `tmp_path` (pytest) — never write to live vault directories.

### Model Selection
- Haiku: ingestion, cleanup, lightweight tagging
- Sonnet: vision, lore, curator, adventure-builder
- Opus: canon validator (high-stakes consistency check) — only on demand, not scheduled

### Backward Compatibility
- New state files must have `init_defaults()` entries in `IStateStore`.
- New `agent.json` fields must be optional with sane defaults so existing agent.json files don't break.
- New tasks added to `tasks-state.json` format must not break existing parsers.

---

## File Inventory (this plan)

| File | Covers |
|------|--------|
| `01-reflexion-loop.md` | Self-critique in Lore agent |
| `02-curator-agent.md` | Semi-automated `02-Library/` promotion |
| `03-cost-tracking.md` | Per-task token and cost recording |
| `04-canon-validator.md` | Canon consistency validation |
| `05-signal-bus.md` | File-based inter-agent event signals |
| `06-adventure-builder.md` | Canon → arc outline synthesis |
| `07-session-builder.md` | Arc + history → session prep |
| `08-semantic-quality.md` | LLM-as-judge quality scoring |
| `09-dedup-agent.md` | Near-duplicate entity detection |
