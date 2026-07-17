# Impl: Curator Agent

**Phase:** P2  
**Priority:** High  
**Effort:** 3 days  
**Depends on:** QualityGate (exists), VaultGuard (exists), FrontmatterIO (exists)

---

## Problem

Every item in `01-Processing/` requires full manual promotion by the human DM. At steady state the pipeline generates many drafts per day (NPCs, wiki pages, classified images). Manual promotion of each item is unsustainable. The bottleneck is not quality - QualityGate can already compute a deterministic score. The bottleneck is the absence of anything that acts on that score.

The `ICurator` interface already exists in `shared/interfaces.py:502`. Nothing implements it.

---

## Goal

The Curator Agent scans `01-Processing/`, scores each file with `QualityGate`, and for files scoring ≥ 7 with all required metadata present: copies the file to `02-Library/` with `status: review` (NOT `status: approved`). The human DM then sets `reviewed: true` + `status: approved` - a single-field edit, not a full review from scratch.

Files scoring < 7 are left in `01-Processing/` with a `curator_notes` frontmatter field explaining what is missing.

The Curator never sets `reviewed: true`. It never sets `status: approved`. VaultGuard enforcement remains unchanged.

---

## Pipeline Position

```
01-Processing/  ──►  Curator (scores, copies)  ──►  02-Library/ (status: review)
                                                             │
                                               Human sets: reviewed: true
                                                            status: approved
```

---

## Scope

Files to create:
- `agents/curator/agent.json`
- `agents/curator/AGENT.md`
- `agents/curator/tools/__init__.py`
- `agents/curator/tools/curator_agent.py`
- `agents/curator/prompts/system.md`
- `agents/curator/state/curator-state.json` (tracks already-assessed files)
- `agents/tests/test_curator.py`

Files to modify:
- `agents/shared/interfaces.py` - `ICurator` already defined; `CuratorSuggestion` model may need `curator_notes` field

---

## `agent.json`

```json
{
  "tasks": {
    "curator-agent": {
      "intervalSeconds": 3600,
      "description": "Score 01-Processing drafts; promote qualifying files to 02-Library/ as status:review",
      "dispatch": {
        "type": "claude-api",
        "claude_api": {
          "model": "claude-sonnet-4-6",
          "system_file": "prompts/system.md",
          "tools_module": "curator.tools.curator_agent",
          "history_file": "curator-agent-history.json",
          "max_tokens": 2048,
          "timeout_seconds": 300,
          "max_tool_rounds": 25
        }
      }
    }
  }
}
```

---

## `AGENT.md`

```yaml
---
name: curator
purpose: >
  Scores 01-Processing/ drafts with QualityGate. Copies qualifying files
  (score >= 7, metadata complete) to 02-Library/ with status: review.
  Human sets reviewed: true + status: approved.
inputs:
  - 01-Processing/
outputs:
  - 02-Library/  (status: review only - never status: approved)
dependencies:
  - lore
  - wiki
  - classification
dispatch_config: agent.json
owned_tools:
  - list_processing_drafts
  - score_draft
  - promote_to_library
  - annotate_with_curator_notes
  - write_log
responsibilities:
  - Score all unassessed .md files in 01-Processing/
  - Copy score>=7 files to 02-Library/ with status: review
  - Write curator_notes to score<7 files explaining gaps
  - Track assessed files in curator-state.json to avoid re-assessing
restrictions:
  - Never set reviewed: true
  - Never set status: approved
  - Never modify 00-Inbox/
  - Never overwrite an existing 02-Library/ file
  - If 02-Library/{slug}.md already exists, skip - do not overwrite canon
state_files:
  - agents/curator/state/curator-state.json
commit_scope:
  - knowledge-base/02-Library
  - agents/curator/state
```

---

## Tools

### `list_processing_drafts() → list[DraftInfo]`

Scans `01-Processing/` for `.md` files. Returns those not yet in `curator-state.json`.

```python
@dataclass
class DraftInfo:
    path: Path
    slug: str
    frontmatter: dict
    body: str
    score: int          # pre-computed by QualityGate
    is_promotable: bool # score >= 7 AND type set AND source set AND has wikilinks
```

### `score_draft(path: str) → ScoringResult`

Reads file, runs `QualityGate.score()`, returns detailed breakdown:

```python
@dataclass
class ScoringResult:
    path: str
    score: int
    dimensions: dict[str, bool]  # {"description": True, "wikilinks": False, ...}
    is_promotable: bool
    missing: list[str]           # human-readable gap list
```

### `promote_to_library(path: str) → PromotionResult`

Steps:
1. `VaultGuard.assert_writable(target)` - verifies target is in `02-Library/`, not `00-Inbox/`
2. Check `02-Library/{slug}.md` does NOT exist. If it does: skip, log warning, return `skipped=True`.
3. Read frontmatter + body from `01-Processing/{slug}.md`
4. Set `frontmatter["status"] = "review"` (not "approved")
5. Set `frontmatter["curator_promoted"] = True`
6. Set `frontmatter["curator_promoted_at"] = datetime.now().isoformat()`
7. Remove `needs_human_review` if present (curator has assessed it)
8. Write to `02-Library/{slug}.md` using `FrontmatterIO.write()` (atomic)
9. Append slug to `curator-state.json` as promoted

```python
@dataclass
class PromotionResult:
    slug: str
    promoted: bool
    skipped: bool       # True if already exists in 02-Library/
    reason: str         # "already_exists" | "promoted" | "vault_guard_blocked"
```

### `annotate_with_curator_notes(path: str, gaps: list[str]) → None`

For score < 7 files. Adds/updates `curator_notes` in frontmatter:

```yaml
curator_notes: "Score 4/10. Missing: ## Description section, wikilinks to location/faction, minimum 3 tags."
curator_assessed: true
curator_assessed_at: "2026-06-10T12:00:00"
```

Does NOT change `status` or `reviewed`. File stays in `01-Processing/`.

### `write_log(promoted: int, skipped: int, annotated: int, failed: int) → None`

Writes standard `--- DONE ---` log line via shared logger.

---

## System Prompt (`agents/curator/prompts/system.md`)

```markdown
# Curator Agent

You are the Curator for a Dungeon Master knowledge vault.
Your role: promote qualifying drafts from 01-Processing/ to 02-Library/ for human final approval.

## Workflow

On each run:
1. Call `list_processing_drafts` - get unassessed .md files with pre-computed scores
2. For each file with `is_promotable: true`: call `promote_to_library`
3. For each file with `is_promotable: false`: call `annotate_with_curator_notes` with the gap list
4. Call `write_log` with counts

## Rules

- NEVER set reviewed: true - human-only field
- NEVER set status: approved - human-only transition
- If 02-Library/{slug}.md already exists: skip it, never overwrite
- Only promote files where is_promotable is true from list_processing_drafts
- Write curator_notes for every non-promotable file so the human knows what to fix
```

---

## State File: `curator-state.json`

```json
{
  "assessed": {
    "npc-warrior-annun": {
      "assessed_at": "2026-06-10T12:00:00Z",
      "score": 8,
      "promoted": true,
      "promoted_at": "2026-06-10T12:00:01Z"
    },
    "location-tavern-south": {
      "assessed_at": "2026-06-10T12:00:00Z",
      "score": 4,
      "promoted": false,
      "notes": "Missing wikilinks, fewer than 3 tags"
    }
  }
}
```

Default (empty): `{"assessed": {}}`.

Re-assessment trigger: if `01-Processing/{slug}.md` `updated` date is newer than `assessed_at`, re-assess. This handles the case where a human fixed the draft after receiving curator notes.

---

## VaultGuard Interaction

The Curator writes to `02-Library/`. `VaultGuard.assert_writable()` currently blocks all writes to `02-Library/` (agents may not write directly). The Curator is an exception.

Two options:
1. Add a `trusted_agents` list to `VaultGuard` - Curator is whitelisted.
2. Curator bypasses VaultGuard and enforces its own constraints directly.

**Decision:** Option 2. The Curator explicitly checks `status: review` (never `approved`) and checks for pre-existing files before writing. The guard on `02-Library/` in VaultGuard protects against uncontrolled writes; the Curator is a controlled write. Document this exception in `AGENT.md` `restrictions` section and add a comment to `vault_guard.py`.

Do NOT modify VaultGuard logic - it protects other agents. The Curator skips the VaultGuard call for its promotion write only.

---

## Tests

`agents/tests/test_curator.py`:

```python
def test_promotes_qualifying_draft(tmp_path):
    # Setup: 01-Processing/ file with score >= 7, all metadata
    # Run curator_agent.promote_to_library()
    # Assert: 02-Library/{slug}.md created with status: review
    # Assert: reviewed NOT in frontmatter (or False)
    # Assert: curator-state.json updated

def test_skips_already_existing_library_file(tmp_path):
    # Setup: 02-Library/{slug}.md already exists
    # Run promote_to_library()
    # Assert: existing file unchanged
    # Assert: result.skipped == True

def test_annotates_low_score_draft(tmp_path):
    # Setup: 01-Processing/ file with score 4
    # Run annotate_with_curator_notes()
    # Assert: curator_notes frontmatter field set
    # Assert: status unchanged (still "draft")
    # Assert: reviewed NOT set to True

def test_never_sets_approved(tmp_path):
    # Run full workflow on high-score file
    # Assert: status == "review", never "approved"
    # Assert: reviewed is False or absent

def test_reassesses_updated_draft(tmp_path):
    # Setup: state.json has slug assessed_at T1
    # Processing/ file has updated T2 > T1
    # Assert: file is re-assessed (not skipped)
```

---

## Success Criteria

- Qualifying drafts appear in `02-Library/` with `status: review` within one Curator run.
- No file in `02-Library/` ever has `status: approved` set by the Curator.
- No file in `02-Library/` ever has `reviewed: true` set by the Curator.
- Existing canon files in `02-Library/` are never overwritten.
- Low-score drafts receive `curator_notes` explaining specific gaps.
- Human promotion path reduces to: open file → change `status: review` to `status: approved` → set `reviewed: true`.
