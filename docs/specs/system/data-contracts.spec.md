# Spec - Data Contracts

---

## Frontmatter Standard

All `01-Processing/` and `02-Library/` entities:

```yaml
---
id: {type}-{slug}
type: npc | character | faction | location | city | village | dungeon | item | artifact | quest | encounter | creature | monster | event | religion | organization | timeline | lore
status: draft | review | approved | archived
quality: 0-10
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags:
  - tag1
source:
  - filename.ext
sha256: {hex string}          # image-derived entities only
reviewed: false               # only humans set true
relationships:
  - "[[entity-slug]]"
---
```

**Quality gate for `02-Library/` promotion:** `status: approved` + `quality >= 7` + `reviewed: true`.  
No agent may write these fields as `true` / `approved`.

---

## Entity Naming (Slug Format)

```
{type}-{descriptor1}-{descriptor2}.md
```

Examples:
- `npc-necromancer-black-hollow.md`
- `location-dungeon-cirit-01.md`
- `battlemap-dungeon-cirit-01.md`

Forbidden patterns: `final_v2`, `new`, `cool`, `Untitled`, uppercase, spaces (except arc folder names like `A9 Desert`).

---

## Logging Format

Every log line:

```
[YYYY-MM-DD HH:mm:ss] [{task-id}] {message}
```

Every agent script emits `--- START ---` and `--- DONE ---` markers.

`--- DONE ---` line format (for metrics parsing):

```
--- DONE (classified: N, failed: N, elapsed: N.Ns) ---
```

Supported item-count keywords: `classified`, `enriched`, `repairs`, `processed`, `converted`, `generated`, `linked`.  
Supported failure-count keywords: `failed`, `failures`.

| File | Content |
|------|---------|
| `agents/runtime/state/logs/automation.log` | Consolidated all-agent log |
| `agents/{name}/state/logs/{script-basename}_YYYY-MM-DD.log` | Per-agent daily rotation |

---

## Encoding

All file I/O must use UTF-8 explicitly:

- PowerShell: `-Encoding UTF8` on every `Get-Content`, `Set-Content`, `Add-Content`
- Python: `encoding='utf-8'` on every file open; stdout wrapped with `io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')` on Windows

BOM stripping required when reading `agent-metrics.json` (Windows PS may emit BOM).
