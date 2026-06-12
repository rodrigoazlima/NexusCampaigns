# Vault Knowledge Factory — First Run Report

**Date:** 2026-06-12  
**Monitor window:** 03:34:29 → 03:44:35 (local, UTC-3) — 10 minutes  
**Daemon PID:** 6464  
**Install method:** HKCU Run key (no-admin, auto-starts at user login)

---

## Service Installation

| Property | Value |
|----------|-------|
| Auto-start | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\VaultKnowledgeFactory` |
| Command | `pwsh.exe -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File daemon.ps1` |
| Auth | OAuth token loaded from `~/.claude/.credentials.json` |
| Daemon uptime | Running (PID 6464, CPU=0.7s, Mem=88.8 MB) |
| Setup script | `.agents/runtime/tools/setup-service.ps1` |

---

## Runtime Activity (10-minute window)

### Daemon cycles

| Time (local) | Event |
|---|---|
| 03:34:29 | Daemon started (PID 6464) |
| 03:34:30 | Cycle 1 — all agents skipped (timestamps not yet reset) |
| 03:35:30 | **Cycle 2 — full run: all 11 agents dispatched** |
| 03:36:33 | Cycle 2 complete (elapsed: 62.41s) |
| 03:37:33–03:44:35 | Cycles 3–11 — all agents skipped (not due, intervals not elapsed) |

**Total runner invocations:** 11  
**Active cycles:** 1  
**Idle cycles:** 10 (correct — all hourly agents just ran, next due at 04:35)

---

## Agent Run Summary (First Active Cycle — 03:35:30 UTC)

| Agent | Duration | Items | Result |
|-------|----------|-------|--------|
| repair-agent | 11.76s | 0 repaired | No stale locks; 11 agents flagged overdue (epoch reset expected) |
| ingestion-agent | 3.86s | 0 | Inbox current — no new files to ingest |
| vision-agent | 3.47s | 0 | No pending images in `00-Inbox/images/` |
| lore-agent | 3.90s | 0 | No image×scenario pairs to process |
| token-agent | 3.82s | 0 | No portrait queue entries |
| wiki-agent | 5.23s | 0 | No pending docs to synthesise |
| classification-agent | 3.92s | 0 | No notes requiring tag enrichment |
| review-agent | 9.51s | 0 | Health report written; report-2026-06-12.json |
| review-agent-short-files | 3.97s | 0 | No short files in `01-Processing/` |
| wikilink-agent | 3.94s | 0 | Library empty — no cross-links to insert |
| cleanup-agent | 7.83s | 0 | No expired logs or metrics to purge |
| **TOTAL** | **62.41s** | **0** | All agents healthy |

All 11 agents exited with `processed: 1, failed: 0`.

---

## Vault Health

| Folder | Files | Status |
|--------|-------|--------|
| `00-Inbox/` | 5 | Awaiting ingestion trigger |
| `01-Processing/` | 0 | Empty |
| `02-Library/` | 0 | Empty — no approved content yet |
| `03-Campaigns/` | 0 | Empty |
| `04-Relationships/` | 0 | Empty |
| `05-Assets/` | 32 | Token frames and art assets present |
| `99-Archive/` | 0 | Empty |

**review-agent metrics (from report-2026-06-12.json):**

| Metric | Value |
|--------|-------|
| pendingReview | 0 |
| orphans | 0 |
| libraryLinkViolations | 0 |
| queueDepth | 5 pending, 0 done |

---

## Cumulative Agent Run History

| Agent | Total runs (all time) | Errors | Warnings |
|-------|-----------------------|--------|----------|
| repair-agent | 5 | 1 | 56 (overdue flags, expected during dev) |
| ingestion-agent | 5 | 0 | 0 |
| vision-agent | 7 | 2 | 0 |
| lore-agent | 6 | 1 | 0 |
| token-agent | 5 | 0 | 0 |
| wiki-agent | 6 | 1 | 0 |
| classification-agent | 5 | 0 | 0 |
| review-agent | 5 | 0 | 0 |
| review-agent-short-files | 5 | 0 | 0 |
| wikilink-agent | 5 | 0 | 0 |
| cleanup-agent | 4 | 0 | 0 |

Errors in vision, lore, wiki agents occurred in prior sessions during model debugging (Sonnet rate-limits). All resolved by switching to Haiku.

---

## Known Limitations

- **NSSM not available** — service runs as a user-level HKCU Run entry, not a Windows Service. Starts only when this user logs in. For always-on production use, install NSSM as Administrator: `winget install NSSM.NSSM` then re-run `setup-service.ps1 -Method nssm`.
- **OAuth token expiry** — daemon auto-refreshes the token from `~/.claude/.credentials.json` each loop iteration. If the token expires while the machine is idle and Claude Code is not running, the next Claude-dispatched agent will fail with a 401 until the token is refreshed.
- **Idle vault** — all agents ran but found nothing to process. The pipeline is ready; results will appear once material is dropped into `00-Inbox/`.

---

## How to Monitor

```powershell
# Live log tail
Get-Content 'C:\opt\GitHub\NexusCampaigns\.agents\runtime\state\logs\automation.log' -Tail 50 -Wait

# Status check
pwsh -File '.agents\runtime\tools\setup-service.ps1' -Status

# Uninstall
pwsh -File '.agents\runtime\tools\setup-service.ps1' -Uninstall
```
