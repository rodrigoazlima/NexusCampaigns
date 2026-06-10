# Impl: Canon Validator Agent

**Phase:** P2  
**Priority:** Medium  
**Effort:** 2 days  
**Depends on:** FrontmatterIO (exists), slug_utils (exists)

---

## Problem

As `02-Library/` grows, silent consistency issues accumulate:
- Wikilinks point to slugs that no longer exist
- Duplicate `id` fields across entities
- Entities reference relationships to archived or renamed entities
- Files promoted by Curator (future) or human may skip metadata requirements

There is no agent that reads `02-Library/` as a whole and validates its consistency. The `ICanonValidator` interface exists in `shared/interfaces.py:466` and the `CanonReport` model exists but neither is implemented.

---

## Goal

A daily Canon Validator Agent scans all `02-Library/` entities and produces a `CanonReport` with:
- **Broken links:** wikilinks in frontmatter `relationships` or body pointing to non-existent slugs
- **Duplicate IDs:** two or more files share the same `id` frontmatter value
- **Missing metadata:** required fields absent (`id`, `type`, `status`, `reviewed`, `relationships`)
- **Orphan entities:** entities with no inbound OR outbound wikilinks
- **Status violations:** files in `02-Library/` with `status: draft` or `reviewed: false`

The agent is read-only. It never modifies `02-Library/`. It writes reports only.

---

## Scope

Files to create:
- `.agents/canon/agent.json`
- `.agents/canon/AGENT.md`
- `.agents/canon/tools/__init__.py`
- `.agents/canon/tools/canon_agent.py`
- `.agents/canon/prompts/system.md`
- `.agents/tests/test_canon_validator.py`

Files to modify:
- `.agents/shared/interfaces.py` — `ICanonValidator` already defined; verify `CanonReport` model is complete
- `.agents/review/tools/daily_report.py` — include canon report in daily summary

---

## `agent.json`

```json
{
  "tasks": {
    "canon-agent": {
      "intervalSeconds": 86400,
      "description": "Daily canon consistency check: broken links, duplicate IDs, orphan entities, status violations",
      "dispatch": {
        "type": "claude-api",
        "claude_api": {
          "model": "claude-sonnet-4-6",
          "system_file": "prompts/system.md",
          "tools_module": "canon.tools.canon_agent",
          "history_file": "canon-agent-history.json",
          "max_tokens": 4096,
          "timeout_seconds": 300,
          "max_tool_rounds": 10
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
name: canon
purpose: >
  Daily read-only consistency check of 02-Library/. Detects broken wikilinks,
  duplicate IDs, orphan entities, missing metadata, and status violations.
  Writes CanonReport to .agents/review/state/reports/.
inputs:
  - knowledge-base/02-Library/
outputs:
  - .agents/review/state/reports/canon-{date}.json
dependencies: []
dispatch_config: agent.json
owned_tools:
  - scan_library
  - build_slug_index
  - detect_broken_links
  - detect_duplicate_ids
  - detect_orphans
  - detect_status_violations
  - write_report
responsibilities:
  - Read all .md files in 02-Library/
  - Build slug index (slug → path)
  - Check all [[wikilinks]] resolve against slug index
  - Check all id fields are unique
  - Check required metadata fields present
  - Check status/reviewed consistency
  - Write CanonReport JSON
restrictions:
  - Read-only. Never modify any file.
  - Never write to 02-Library/
  - Never write to 00-Inbox/
  - Never write to 01-Processing/
state_files: []
commit_scope:
  - .agents/review/state/reports
```

---

## Data Model: `CanonReport`

Extend or verify in `shared/models.py` (or wherever `CanonReport` is defined):

```python
@dataclass
class CanonViolation:
    file: str              # relative path from vault root
    slug: str
    violation_type: str    # "broken_link" | "duplicate_id" | "missing_metadata" | "orphan" | "status_violation"
    detail: str            # human-readable description
    severity: str          # "error" | "warning"

@dataclass
class CanonReport:
    date: str
    total_entities: int
    violations: list[CanonViolation]
    error_count: int
    warning_count: int
    healthy: bool          # True if error_count == 0
```

---

## Tools

### `scan_library() → list[EntityScan]`

Reads all `.md` files in `02-Library/` using `FrontmatterIO`. Returns list of:

```python
@dataclass
class EntityScan:
    path: Path
    slug: str              # filename without .md
    frontmatter: dict
    body: str
    wikilinks: list[str]   # all [[slug]] found in relationships + body
```

### `build_slug_index(scans: list[EntityScan]) → dict[str, Path]`

Returns `{slug: path}` for every entity in `02-Library/`. Used to validate wikilinks.

Also includes `02-Library/` subdirectory entities if any are in subfolders.

### `detect_broken_links(scans, slug_index) → list[CanonViolation]`

For each entity, for each wikilink in `relationships` + body: check if target slug is in `slug_index`. If not: emit `violation_type: "broken_link"`, severity `"error"`.

```
"[[npc-wizard-old-tower]]" not found in 02-Library/ — broken link in npc-warrior-annun
```

### `detect_duplicate_ids(scans) → list[CanonViolation]`

Group scans by `frontmatter["id"]`. Any `id` appearing in 2+ files: emit `violation_type: "duplicate_id"`, severity `"error"`, detail lists all conflicting files.

### `detect_missing_metadata(scans) → list[CanonViolation]`

Required fields: `id`, `type`, `status`, `quality`, `created`, `updated`, `reviewed`, `relationships`.

For each missing required field: emit `violation_type: "missing_metadata"`, severity `"warning"`.

### `detect_orphans(scans, slug_index) → list[CanonViolation]`

An orphan is an entity that is:
- Not referenced by any other entity's wikilinks (no inbound links) AND
- Has no outbound wikilinks itself

Emit `violation_type: "orphan"`, severity `"warning"`.

Note: newly promoted entities may be orphans until the Wikilink Agent runs. Consider a grace period: `created` within last 7 days → skip orphan check.

### `detect_status_violations(scans) → list[CanonViolation]`

Checks:
- `status` is not `"approved"` → severity `"error"` (should not be in `02-Library/` if not approved... unless Curator placed it as `"review"`)
- Actually: `02-Library/` may contain `status: review` (Curator placed, awaiting human). These are valid.
- Flag: `status: draft` → severity `"error"` (draft in Library = pipeline bug)
- Flag: `reviewed: false` AND `status: approved` → severity `"error"` (impossible state — approved but not reviewed)
- Flag: `quality < 7` AND `status: approved` → severity `"warning"` (quality degraded after approval)

### `write_report(report: CanonReport) → None`

Writes `CanonReport` as JSON to `.agents/review/state/reports/canon-{date}.json`. Atomic write.

---

## System Prompt (`.agents/canon/prompts/system.md`)

```markdown
# Canon Validator Agent

You are the Canon Validator for a Dungeon Master knowledge vault.
Your role: perform a daily read-only consistency audit of 02-Library/.

## Workflow

1. Call `scan_library` — load all entities with frontmatter and body
2. Call `build_slug_index` — build the slug → path lookup
3. Call `detect_broken_links` with scans and index
4. Call `detect_duplicate_ids` with scans
5. Call `detect_missing_metadata` with scans
6. Call `detect_orphans` with scans and index
7. Call `detect_status_violations` with scans
8. Combine all violations into a CanonReport
9. Call `write_report` with the completed report

## Rules

- Read-only. Never modify any file.
- If 02-Library/ is empty or absent: write an empty healthy report and stop.
- Count errors vs. warnings separately. `healthy: true` only if error_count == 0.
- Log total entity count and violation summary at DONE.
```

---

## Integration with Daily Report

In `review/tools/daily_report.py`, after building the standard report:

```python
canon_report_path = _REPORTS_DIR / f"canon-{today}.json"
if canon_report_path.exists():
    canon_data = json.loads(canon_report_path.read_text(encoding="utf-8"))
    report.canon_violations = canon_data.get("violations", [])
    report.canon_healthy = canon_data.get("healthy", True)
```

The review dashboard already renders JSON reports. Add a "Canon Health" card to `reports-data.js` consuming this.

---

## Tests

`.agents/tests/test_canon_validator.py`:

```python
def test_clean_library_produces_healthy_report(tmp_path):
    # Create 3 linked entities with correct metadata
    # Run validator
    # Assert: healthy=True, violations=[]

def test_detects_broken_wikilink(tmp_path):
    # Entity A links to [[entity-b]] but entity-b.md doesn't exist
    # Assert: violation_type="broken_link", severity="error"

def test_detects_duplicate_ids(tmp_path):
    # Two files share id: "npc-warrior"
    # Assert: violation_type="duplicate_id", severity="error"

def test_detects_draft_in_library(tmp_path):
    # File in 02-Library/ has status: draft
    # Assert: violation_type="status_violation", severity="error"

def test_approved_without_reviewed_flagged(tmp_path):
    # File: status=approved, reviewed=false
    # Assert: violation_type="status_violation", severity="error"

def test_new_entity_orphan_grace_period(tmp_path):
    # Entity created today, no links
    # Assert: no orphan violation (within 7-day grace period)

def test_old_entity_orphan_flagged(tmp_path):
    # Entity created 30 days ago, no inbound or outbound links
    # Assert: violation_type="orphan", severity="warning"

def test_report_written_atomically(tmp_path):
    # Simulate crash during write
    # Assert: no partial report file remains
```

---

## Success Criteria

- Canon report generated daily to `.agents/review/state/reports/canon-{date}.json`.
- Broken wikilinks detected and reported with file + link details.
- Duplicate IDs detected across all `02-Library/` entities.
- Status violations (draft in library, approved-but-not-reviewed) flagged as errors.
- Orphan entities (older than 7 days, no links) flagged as warnings.
- Agent is strictly read-only — zero modifications to any vault files.
- Canon health status surfaced in daily review report.
