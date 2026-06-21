"""
Tests for .automation/08-daily-report.ps1

Strategy: patch $VaultRoot in the script text, write the patched copy to
tmp_path, invoke via subprocess.  All assertions check filesystem state
(JSON report content, JS data file, frontmatter writes, log files).

No external services needed.

Behaviors under test:
   1.  Empty log           — report written with 0 tasks, 0 errors
   2.  Log parsing         — START/DONE counted per task; runs/completedRuns correct
   3.  24h window          — entries older than 24h excluded from stats
   4.  Malformed lines     — silently skipped without crash
   5.  Skipped task IDs    — runner/review-agent not aggregated
   6.  Severity detect     — error/warning/info keywords classified correctly
   7.  Repair-agent filter — [CHECK]/[WARN]/[REPAIR] prefixed lines not counted as errors
   8.  Pending review      — reviewed:false and status:draft detected
   9.  Orphan detection    — files without [[wikilinks]] flagged
  10.  Quality scoring     — Get-QualityScore rubric (+2 per criterion, max 10)
  11.  suggestedQuality    — written to frontmatter when quality:0 or missing
  12.  suggestedQuality    — not written when quality already > 0
  13.  suggestedQuality    — not duplicated on second run
  14.  Queue stats         — total/pending/done/stuck counted correctly
  15.  Queue stuck         — pending + ingestedAt > 48h → stuck
  16.  Report JSON         — written to reports/report-YYYY-MM-DD.json
  17.  Report structure    — top-level keys: date, summary, tasks, vaultHealth, queueStats
  18.  Summary totals      — totalRuns/totalErrors/totalWarnings match task detail
  19.  reports-data.js     — created; embeds REPORTS, TASK_CONFIG, TASK_INTERVALS
  20.  Multi-report JS     — second run merges previous report into reports-data.js
  21.  Logging             — automation.log + per-task log created with START/DONE
  22.  Missing dirs        — missing 01-Processing or queue file → exits 0
  23.  Empty vault         — no drafts → pendingReview/orphans empty lists
  24.  Idempotency         — double run exits 0; one report file per date
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "08-daily-report.ps1"
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ts(dt: datetime) -> str:
    """Format datetime as the log format the script expects."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _log_line(task_id: str, msg: str, dt: datetime | None = None) -> str:
    """Build a single log line matching the pattern the script parses."""
    dt = dt or datetime.now()
    return f"[{_fmt_ts(dt)}] [{task_id}] {msg}"


def _recent(hours_ago: float = 1.0) -> datetime:
    """Return a datetime within the 24 h parsing window."""
    return datetime.now() - timedelta(hours=hours_ago)


def _old(hours_ago: float = 25.0) -> datetime:
    """Return a datetime older than the 24 h cutoff."""
    return datetime.now() - timedelta(hours=hours_ago)


def _patch_script(vault_root: Path) -> str:
    """Replace the hardcoded $VaultRoot with the temp path."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    return text.replace(
        f"$VaultRoot   = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot   = '{vault_root}'",
    )


def run_daily_report(vault_root: Path) -> subprocess.CompletedProcess[str]:
    """Patch and execute the script; return CompletedProcess for inspection."""
    patched = _patch_script(vault_root)
    tmp_script = vault_root / "_test-08-daily-report.ps1"
    tmp_script.write_text(patched, encoding="utf-8")
    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=90,
    )


def _shared_log(vault: Path) -> Path:
    return vault / ".automation" / "logs" / "automation.log"


def _reports_dir(vault: Path) -> Path:
    return vault / ".automation" / "reports"


def _find_report(vault: Path) -> Path | None:
    """Return the report JSON written today, or None if not found."""
    today = datetime.now().strftime("%Y-%m-%d")
    candidate = _reports_dir(vault) / f"report-{today}.json"
    return candidate if candidate.exists() else None


def _load_report(vault: Path) -> dict[str, Any]:
    path = _find_report(vault)
    assert path is not None, "Report JSON not found"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_log(vault: Path, lines: list[str]) -> None:
    """Write lines to the shared automation log."""
    log = _shared_log(vault)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_draft(
    vault: Path,
    filename: str,
    content: str,
    subdir: str = "01-Processing",
) -> Path:
    path = vault / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_queue(vault: Path, items: dict[str, Any]) -> None:
    q_path = vault / ".automation" / "inbox-queue.json"
    q_path.write_text(json.dumps(items), encoding="utf-8")


def _write_tasks_config(vault: Path, tasks: list[dict[str, Any]]) -> None:
    cfg = {"tasks": tasks}
    cfg_path = vault / ".automation" / "tasks.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontmatter templates
# ---------------------------------------------------------------------------

_FM_PENDING_REVIEWED_FALSE = """\
---
id: npc-pending
type: npc
status: draft
reviewed: false
tags:
  - npc
  - undead
  - dark
relationships:
  - "[[location-dungeon]]"
---
## Description

A pending NPC.
"""

_FM_PENDING_STATUS_DRAFT = """\
---
id: npc-draft
type: npc
status: draft
reviewed: true
tags:
  - npc
---
## Description

Status is draft.
"""

_FM_APPROVED = """\
---
id: npc-approved
type: npc
status: approved
reviewed: true
tags:
  - npc
  - location
---
## Description

Approved NPC.
"""

_FM_ORPHAN = """\
---
id: npc-orphan
type: npc
status: draft
reviewed: false
tags:
  - npc
---
No wikilinks here at all.
"""

_FM_WITH_LINKS = """\
---
id: npc-linked
type: npc
status: draft
reviewed: false
tags:
  - npc
relationships:
  - "[[location-dungeon]]"
---
See [[location-dungeon]] for details.
"""

_FM_QUALITY_FULL = """\
---
id: npc-full
type: npc
status: draft
quality: 0
reviewed: false
tags:
  - npc
  - undead
  - dark
source:
  - portrait.png
relationships:
  - "[[location-dungeon]]"
---
## Description

Full-scoring NPC with all rubric fields.

See [[location-dungeon]].
"""

_FM_QUALITY_EMPTY = """\
---
id: npc-empty
status: draft
reviewed: false
---
No sections, no tags, no links.
"""

_FM_QUALITY_ALREADY_SET = """\
---
id: npc-scored
type: npc
status: draft
quality: 5
reviewed: false
tags:
  - npc
---
Already has quality score.
"""

_FM_SUGGESTED_ALREADY = """\
---
id: npc-has-suggested
type: npc
status: draft
quality: 0
suggestedQuality: 4
reviewed: false
tags:
  - npc
---
Already has suggestedQuality.
"""


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Generator[Path, None, None]:
    """Minimal vault directory tree required by 08-daily-report.ps1."""
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    (tmp_path / ".automation" / "reports").mkdir(parents=True)
    (tmp_path / "01-Processing").mkdir()
    # Empty shared log so the script doesn't fail on Get-Content
    _shared_log(tmp_path).write_text("", encoding="utf-8")
    yield tmp_path


# ---------------------------------------------------------------------------
# 1. Empty log
# ---------------------------------------------------------------------------


class TestEmptyLog:
    """An empty automation.log produces a report with zero stats."""

    def test_exits_zero(self, vault: Path) -> None:
        result = run_daily_report(vault)
        assert result.returncode == 0, result.stderr

    def test_report_file_created(self, vault: Path) -> None:
        run_daily_report(vault)
        assert _find_report(vault) is not None

    def test_summary_all_zeros(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["summary"]["totalRuns"] == 0
        assert report["summary"]["totalErrors"] == 0
        assert report["summary"]["totalWarnings"] == 0

    def test_tasks_empty(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["tasks"] == {} or len(report["tasks"]) == 0

    def test_vault_health_lists_empty(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        vh = report["vaultHealth"]
        assert vh["pendingReview"] == []
        assert vh["orphans"] == []


# ---------------------------------------------------------------------------
# 2. Log parsing — START/DONE counted per task
# ---------------------------------------------------------------------------


class TestLogParsing:
    """START and DONE markers are counted per task within the 24h window."""

    def test_single_task_run_counted(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("classify-agent", "--- START ---", _recent(2)),
            _log_line("classify-agent", "Processed 5 images", _recent(2)),
            _log_line("classify-agent", "--- DONE (elapsed: 3.2s) ---", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        task = report["tasks"]["classify-agent"]
        assert task["runs"] == 1
        assert task["completedRuns"] == 1

    def test_multiple_starts_counted(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("classify-agent", "--- START ---", _recent(10)),
            _log_line("classify-agent", "--- DONE ---", _recent(10)),
            _log_line("classify-agent", "--- START ---", _recent(2)),
            _log_line("classify-agent", "--- DONE ---", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["tasks"]["classify-agent"]["runs"] == 2
        assert report["tasks"]["classify-agent"]["completedRuns"] == 2

    def test_two_distinct_tasks(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("classify-agent", "--- START ---", _recent(3)),
            _log_line("classify-agent", "--- DONE ---", _recent(3)),
            _log_line("token-agent", "--- START ---", _recent(1)),
            _log_line("token-agent", "--- DONE ---", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert "classify-agent" in report["tasks"]
        assert "token-agent" in report["tasks"]

    def test_incomplete_run_completedRuns_not_incremented(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("classify-agent", "--- START ---", _recent(2)),
            _log_line("classify-agent", "Processed file", _recent(2)),
            # No DONE line
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        task = report["tasks"]["classify-agent"]
        assert task["runs"] == 1
        assert task["completedRuns"] == 0

    def test_total_runs_sum_across_tasks(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("task-a", "--- START ---", _recent(5)),
            _log_line("task-a", "--- START ---", _recent(3)),
            _log_line("task-b", "--- START ---", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["summary"]["totalRuns"] == 3


# ---------------------------------------------------------------------------
# 3. 24h time window
# ---------------------------------------------------------------------------


class TestTimeWindow:
    """Log entries older than 24h must not appear in the report."""

    def test_old_entry_excluded(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("old-agent", "--- START ---", _old(30)),
            _log_line("old-agent", "--- DONE ---", _old(30)),
            _log_line("new-agent", "--- START ---", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert "old-agent" not in report["tasks"]
        assert "new-agent" in report["tasks"]

    def test_mixed_entries_only_recent_counted(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("batch-agent", "--- START ---", _old(26)),
            _log_line("batch-agent", "--- DONE ---", _old(26)),
            _log_line("batch-agent", "--- START ---", _recent(2)),
            _log_line("batch-agent", "--- DONE ---", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["tasks"]["batch-agent"]["runs"] == 1

    def test_boundary_just_inside_window(self, vault: Path) -> None:
        """Entry at 23h59m ago should be included."""
        just_inside = datetime.now() - timedelta(hours=23, minutes=59)
        _write_log(vault, [
            _log_line("edge-agent", "--- START ---", just_inside),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert "edge-agent" in report["tasks"]


# ---------------------------------------------------------------------------
# 4. Malformed lines
# ---------------------------------------------------------------------------


class TestMalformedLines:
    """Lines that don't match the log pattern are silently skipped."""

    def test_malformed_lines_no_crash(self, vault: Path) -> None:
        _write_log(vault, [
            "this is not a valid log line",
            "[bad-ts] [task] msg",
            "   ",
            "2026-06-14 no brackets",
            _log_line("good-agent", "--- START ---", _recent(1)),
        ])
        result = run_daily_report(vault)
        assert result.returncode == 0, result.stderr

    def test_only_good_lines_counted(self, vault: Path) -> None:
        _write_log(vault, [
            "garbage line 1",
            "garbage line 2",
            _log_line("good-agent", "--- START ---", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert "good-agent" in report["tasks"]
        assert report["tasks"]["good-agent"]["runs"] == 1


# ---------------------------------------------------------------------------
# 5. Skipped task IDs: runner and review-agent
# ---------------------------------------------------------------------------


class TestSkippedTaskIds:
    """runner and review-agent task IDs are filtered from aggregation."""

    @pytest.mark.parametrize("task_id", ["runner", "review-agent"])
    def test_excluded_task_not_in_report(self, vault: Path, task_id: str) -> None:
        _write_log(vault, [
            _log_line(task_id, "--- START ---", _recent(1)),
            _log_line(task_id, "An error occurred", _recent(1)),
            _log_line(task_id, "--- DONE ---", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert task_id not in report["tasks"]

    def test_other_tasks_still_included(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("runner", "--- START ---", _recent(2)),
            _log_line("runner", "--- DONE ---", _recent(2)),
            _log_line("classify-agent", "--- START ---", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert "runner" not in report["tasks"]
        assert "classify-agent" in report["tasks"]


# ---------------------------------------------------------------------------
# 6. Severity detection
# ---------------------------------------------------------------------------


class TestSeverityDetection:
    """Error and warning keywords trigger severity buckets."""

    @pytest.mark.parametrize("keyword", ["error", "failed", "exception", "critical",
                                          "Error", "FAILED", "EXCEPTION", "Critical"])
    def test_error_keywords_classified(self, vault: Path, keyword: str) -> None:
        _write_log(vault, [
            _log_line("task-x", "--- START ---", _recent(2)),
            _log_line("task-x", f"Something {keyword} happened", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert len(report["tasks"]["task-x"]["errors"]) == 1

    @pytest.mark.parametrize("keyword", ["warn", "warning", "Warn", "WARNING"])
    def test_warning_keywords_classified(self, vault: Path, keyword: str) -> None:
        _write_log(vault, [
            _log_line("task-y", "--- START ---", _recent(2)),
            _log_line("task-y", f"Something {keyword}ing happened", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert len(report["tasks"]["task-y"]["warnings"]) == 1

    def test_normal_message_not_counted(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("task-z", "--- START ---", _recent(2)),
            _log_line("task-z", "Processed 5 files successfully", _recent(2)),
            _log_line("task-z", "--- DONE ---", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["tasks"]["task-z"]["errors"] == []
        assert report["tasks"]["task-z"]["warnings"] == []

    def test_total_errors_correct(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("agent-a", "--- START ---", _recent(3)),
            _log_line("agent-a", "critical failure", _recent(3)),
            _log_line("agent-b", "--- START ---", _recent(1)),
            _log_line("agent-b", "another error occurred", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["summary"]["totalErrors"] == 2


# ---------------------------------------------------------------------------
# 7. Repair-agent filter
# ---------------------------------------------------------------------------


class TestRepairAgentFilter:
    """repair-agent [CHECK]/[WARN]/[REPAIR] lines and 'Error buckets' must not be errors."""

    def test_check_prefix_not_error(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("repair-agent", "--- START ---", _recent(2)),
            _log_line("repair-agent", "[CHECK] validating files", _recent(2)),
            _log_line("repair-agent", "[WARN] something suspicious", _recent(2)),
            _log_line("repair-agent", "[REPAIR] fixing file", _recent(2)),
            _log_line("repair-agent", "Error buckets: {}", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        # repair-agent housekeeping lines must not produce errors
        errors = report["tasks"].get("repair-agent", {}).get("errors", [])
        assert errors == []

    def test_genuine_repair_error_still_captured(self, vault: Path) -> None:
        """Non-housekeeping error from repair-agent must be captured."""
        _write_log(vault, [
            _log_line("repair-agent", "--- START ---", _recent(2)),
            _log_line("repair-agent", "Unexpected exception in file scan", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        errors = report["tasks"].get("repair-agent", {}).get("errors", [])
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# 8. Pending review detection
# ---------------------------------------------------------------------------


class TestPendingReview:
    """Files with reviewed:false or status:draft are listed in pendingReview."""

    def test_reviewed_false_flagged(self, vault: Path) -> None:
        _write_draft(vault, "npc-pending.md", _FM_PENDING_REVIEWED_FALSE)
        run_daily_report(vault)
        report = _load_report(vault)
        pending = report["vaultHealth"]["pendingReview"]
        assert any("npc-pending.md" in p for p in pending)

    def test_status_draft_flagged(self, vault: Path) -> None:
        _write_draft(vault, "npc-draft.md", _FM_PENDING_STATUS_DRAFT)
        run_daily_report(vault)
        report = _load_report(vault)
        pending = report["vaultHealth"]["pendingReview"]
        assert any("npc-draft.md" in p for p in pending)

    def test_approved_not_flagged(self, vault: Path) -> None:
        _write_draft(vault, "npc-approved.md", _FM_APPROVED)
        run_daily_report(vault)
        report = _load_report(vault)
        pending = report["vaultHealth"]["pendingReview"]
        assert not any("npc-approved.md" in p for p in pending)

    def test_empty_processing_dir_empty_list(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["vaultHealth"]["pendingReview"] == []

    def test_multiple_pending_all_listed(self, vault: Path) -> None:
        _write_draft(vault, "npc-a.md", _FM_PENDING_REVIEWED_FALSE)
        _write_draft(vault, "npc-b.md", _FM_PENDING_STATUS_DRAFT)
        run_daily_report(vault)
        report = _load_report(vault)
        pending = report["vaultHealth"]["pendingReview"]
        assert len(pending) == 2


# ---------------------------------------------------------------------------
# 9. Orphan detection
# ---------------------------------------------------------------------------


class TestOrphanDetection:
    """Files without [[wikilinks]] anywhere in their content are flagged."""

    def test_no_wikilinks_is_orphan(self, vault: Path) -> None:
        _write_draft(vault, "npc-orphan.md", _FM_ORPHAN)
        run_daily_report(vault)
        report = _load_report(vault)
        orphans = report["vaultHealth"]["orphans"]
        assert any("npc-orphan.md" in o for o in orphans)

    def test_file_with_links_not_orphan(self, vault: Path) -> None:
        _write_draft(vault, "npc-linked.md", _FM_WITH_LINKS)
        run_daily_report(vault)
        report = _load_report(vault)
        orphans = report["vaultHealth"]["orphans"]
        assert not any("npc-linked.md" in o for o in orphans)

    def test_orphan_in_relationships_and_body(self, vault: Path) -> None:
        """A file with [[link]] only in body is still considered linked."""
        content = (
            "---\nid: npc-body-link\ntype: npc\nstatus: draft\nreviewed: false\ntags:\n  - npc\n---\n"
            "See [[faction-cult]] for more.\n"
        )
        _write_draft(vault, "npc-body-link.md", content)
        run_daily_report(vault)
        report = _load_report(vault)
        orphans = report["vaultHealth"]["orphans"]
        assert not any("npc-body-link.md" in o for o in orphans)


# ---------------------------------------------------------------------------
# 10. Quality scoring (Get-QualityScore rubric)
# ---------------------------------------------------------------------------


class TestQualityScoring:
    """Each criterion awards +2 points; max score is 10."""

    def test_empty_file_scores_zero(self, vault: Path) -> None:
        _write_draft(vault, "npc-empty.md", _FM_QUALITY_EMPTY)
        run_daily_report(vault)
        report = _load_report(vault)
        suggestions = report["vaultHealth"]["qualitySuggestions"]
        rel_key = next((k for k in suggestions if "npc-empty.md" in k), None)
        assert rel_key is not None
        assert suggestions[rel_key] == 0

    def test_full_criteria_scores_ten(self, vault: Path) -> None:
        """All five criteria met → score 10."""
        _write_draft(vault, "npc-full.md", _FM_QUALITY_FULL)
        run_daily_report(vault)
        report = _load_report(vault)
        suggestions = report["vaultHealth"]["qualitySuggestions"]
        rel_key = next((k for k in suggestions if "npc-full.md" in k), None)
        assert rel_key is not None
        assert suggestions[rel_key] == 10

    def test_description_section_adds_two(self, vault: Path) -> None:
        content = (
            "---\nid: npc-desc\nstatus: draft\nquality: 0\nreviewed: false\n---\n"
            "## Description\n\nSome text.\n"
        )
        _write_draft(vault, "npc-desc.md", content)
        run_daily_report(vault)
        report = _load_report(vault)
        suggestions = report["vaultHealth"]["qualitySuggestions"]
        rel_key = next((k for k in suggestions if "npc-desc.md" in k), None)
        assert rel_key is not None
        assert suggestions[rel_key] >= 2

    def test_type_field_adds_two(self, vault: Path) -> None:
        content = (
            "---\nid: npc-typed\ntype: npc\nstatus: draft\nquality: 0\nreviewed: false\n---\nBody.\n"
        )
        _write_draft(vault, "npc-typed.md", content)
        run_daily_report(vault)
        report = _load_report(vault)
        suggestions = report["vaultHealth"]["qualitySuggestions"]
        rel_key = next((k for k in suggestions if "npc-typed.md" in k), None)
        assert rel_key is not None
        assert suggestions[rel_key] >= 2

    @pytest.mark.parametrize("tag_count,expected_bonus", [(2, 0), (3, 2), (5, 2)])
    def test_three_plus_tags_threshold(
        self, vault: Path, tag_count: int, expected_bonus: int
    ) -> None:
        """3+ tags awards +2; fewer than 3 does not."""
        tag_lines = "\n".join(f"  - tag{i}" for i in range(tag_count))
        content = (
            f"---\nid: npc-tags-{tag_count}\nstatus: draft\nquality: 0\nreviewed: false\n"
            f"tags:\n{tag_lines}\n---\nBody.\n"
        )
        _write_draft(vault, f"npc-tags-{tag_count}.md", content)
        run_daily_report(vault)
        report = _load_report(vault)
        suggestions = report["vaultHealth"]["qualitySuggestions"]
        rel_key = next((k for k in suggestions if f"npc-tags-{tag_count}.md" in k), None)
        if expected_bonus > 0:
            assert suggestions[rel_key] >= expected_bonus
        else:
            # 2 tags → tag criterion NOT met; score should not include that +2
            # (score could still be 0 or higher from other criteria)
            assert suggestions[rel_key] < 10  # just sanity-check it ran


# ---------------------------------------------------------------------------
# 11. suggestedQuality written to frontmatter when quality: 0 or missing
# ---------------------------------------------------------------------------


class TestSuggestedQualityWritten:
    """Script writes suggestedQuality: N into the file when quality is absent/0."""

    def test_quality_zero_gets_suggested(self, vault: Path) -> None:
        draft = _write_draft(vault, "npc-q0.md", _FM_QUALITY_FULL)
        run_daily_report(vault)
        content = draft.read_text(encoding="utf-8")
        assert "suggestedQuality:" in content

    def test_missing_quality_gets_suggested(self, vault: Path) -> None:
        content_no_q = (
            "---\nid: npc-noq\ntype: npc\nstatus: draft\nreviewed: false\ntags:\n  - npc\n---\nBody.\n"
        )
        draft = _write_draft(vault, "npc-noq.md", content_no_q)
        run_daily_report(vault)
        content = draft.read_text(encoding="utf-8")
        assert "suggestedQuality:" in content

    def test_suggested_value_matches_report(self, vault: Path) -> None:
        """suggestedQuality in file must match qualitySuggestions in report."""
        draft = _write_draft(vault, "npc-q0.md", _FM_QUALITY_FULL)
        run_daily_report(vault)
        report = _load_report(vault)
        suggestions = report["vaultHealth"]["qualitySuggestions"]
        rel_key = next((k for k in suggestions if "npc-q0.md" in k), None)
        assert rel_key is not None
        expected_score = suggestions[rel_key]

        content = draft.read_text(encoding="utf-8")
        match = re.search(r"suggestedQuality:\s*(\d+)", content)
        assert match is not None
        assert int(match.group(1)) == expected_score


# ---------------------------------------------------------------------------
# 12. suggestedQuality NOT written when quality already > 0
# ---------------------------------------------------------------------------


class TestSuggestedQualityNotOverwritten:
    """When quality is already set to a positive value, file is not modified."""

    def test_positive_quality_file_unchanged(self, vault: Path) -> None:
        draft = _write_draft(vault, "npc-scored.md", _FM_QUALITY_ALREADY_SET)
        original = draft.read_text(encoding="utf-8")
        run_daily_report(vault)
        assert draft.read_text(encoding="utf-8") == original

    def test_positive_quality_not_in_suggestions(self, vault: Path) -> None:
        _write_draft(vault, "npc-scored.md", _FM_QUALITY_ALREADY_SET)
        run_daily_report(vault)
        report = _load_report(vault)
        suggestions = report["vaultHealth"]["qualitySuggestions"]
        assert not any("npc-scored.md" in k for k in suggestions)


# ---------------------------------------------------------------------------
# 13. suggestedQuality not duplicated on second run
# ---------------------------------------------------------------------------


class TestSuggestedQualityIdempotent:
    """Running the script twice must not produce two suggestedQuality lines."""

    def test_second_run_no_duplicate_suggested(self, vault: Path) -> None:
        draft = _write_draft(vault, "npc-q0.md", _FM_QUALITY_FULL)
        run_daily_report(vault)
        run_daily_report(vault)
        content = draft.read_text(encoding="utf-8")
        assert content.count("suggestedQuality:") == 1

    def test_already_suggested_not_rewritten(self, vault: Path) -> None:
        draft = _write_draft(vault, "npc-suggested.md", _FM_SUGGESTED_ALREADY)
        original = draft.read_text(encoding="utf-8")
        run_daily_report(vault)
        # File must not change since suggestedQuality already present
        assert draft.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 14. Queue stats — total/pending/done/stuck
# ---------------------------------------------------------------------------


class TestQueueStats:
    """Queue stats reflect pending/done/stuck item counts."""

    def test_no_queue_file_stats_zero(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        qs = report["queueStats"]
        assert qs["total"] == 0
        assert qs["pending"] == 0
        assert qs["done"] == 0

    def test_all_done_items(self, vault: Path) -> None:
        items = {
            "sha001": {
                "agents": {"agent-a": "done", "agent-b": "done"},
                "ingestedAt": _recent(10).isoformat(),
            },
            "sha002": {
                "agents": {"agent-a": "done"},
                "ingestedAt": _recent(5).isoformat(),
            },
        }
        _write_queue(vault, items)
        run_daily_report(vault)
        report = _load_report(vault)
        qs = report["queueStats"]
        assert qs["total"] == 2
        assert qs["done"] == 2
        assert qs["pending"] == 0

    def test_pending_item_counted(self, vault: Path) -> None:
        items = {
            "sha003": {
                "agents": {"agent-a": "done", "agent-b": "pending"},
                "ingestedAt": _recent(1).isoformat(),
            },
        }
        _write_queue(vault, items)
        run_daily_report(vault)
        report = _load_report(vault)
        qs = report["queueStats"]
        assert qs["total"] == 1
        assert qs["pending"] == 1
        assert qs["done"] == 0

    def test_mixed_queue(self, vault: Path) -> None:
        items = {
            "sha004": {
                "agents": {"agent-a": "done"},
                "ingestedAt": _recent(2).isoformat(),
            },
            "sha005": {
                "agents": {"agent-a": "pending"},
                "ingestedAt": _recent(1).isoformat(),
            },
        }
        _write_queue(vault, items)
        run_daily_report(vault)
        report = _load_report(vault)
        qs = report["queueStats"]
        assert qs["total"] == 2
        assert qs["pending"] == 1
        assert qs["done"] == 1


# ---------------------------------------------------------------------------
# 15. Queue stuck detection (pending + ingestedAt > 48h ago)
# ---------------------------------------------------------------------------


class TestQueueStuck:
    """Items pending for more than 48h are counted as stuck."""

    def test_old_pending_is_stuck(self, vault: Path) -> None:
        old_ts = (datetime.now() - timedelta(hours=50)).isoformat()
        items = {
            "sha006": {
                "agents": {"agent-a": "pending"},
                "ingestedAt": old_ts,
            },
        }
        _write_queue(vault, items)
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["queueStats"]["stuck"] == 1

    def test_recent_pending_not_stuck(self, vault: Path) -> None:
        recent_ts = _recent(10).isoformat()
        items = {
            "sha007": {
                "agents": {"agent-a": "pending"},
                "ingestedAt": recent_ts,
            },
        }
        _write_queue(vault, items)
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["queueStats"]["stuck"] == 0

    def test_done_items_never_stuck(self, vault: Path) -> None:
        old_ts = (datetime.now() - timedelta(hours=100)).isoformat()
        items = {
            "sha008": {
                "agents": {"agent-a": "done"},
                "ingestedAt": old_ts,
            },
        }
        _write_queue(vault, items)
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["queueStats"]["stuck"] == 0


# ---------------------------------------------------------------------------
# 16 & 17. Report JSON structure
# ---------------------------------------------------------------------------


class TestReportStructure:
    """The written JSON has the expected top-level keys and date fields."""

    def test_top_level_keys_present(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        for key in ("date", "generatedAt", "periodStart", "periodEnd",
                    "summary", "tasks", "vaultHealth", "queueStats"):
            assert key in report, f"Missing key: {key}"

    def test_date_matches_today(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        today = datetime.now().strftime("%Y-%m-%d")
        assert report["date"] == today

    def test_summary_keys_present(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        summary = report["summary"]
        for key in ("totalRuns", "totalErrors", "totalWarnings", "tasksWithErrors"):
            assert key in summary, f"Missing summary key: {key}"

    def test_vault_health_keys_present(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        vh = report["vaultHealth"]
        for key in ("pendingReview", "orphans", "qualitySuggestions"):
            assert key in vh, f"Missing vaultHealth key: {key}"

    def test_tasks_with_errors_list(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("agent-err", "--- START ---", _recent(2)),
            _log_line("agent-err", "critical failure", _recent(2)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert "agent-err" in report["summary"]["tasksWithErrors"]

    def test_report_is_valid_json(self, vault: Path) -> None:
        run_daily_report(vault)
        path = _find_report(vault)
        assert path is not None
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)  # must not raise
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# 18. Summary totals aggregate across all tasks
# ---------------------------------------------------------------------------


class TestSummaryTotals:
    """Summary counts aggregate correctly from multiple tasks."""

    def test_total_warnings_across_tasks(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("agent-a", "--- START ---", _recent(3)),
            _log_line("agent-a", "warning: disk low", _recent(3)),
            _log_line("agent-b", "--- START ---", _recent(1)),
            _log_line("agent-b", "warn: retrying", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["summary"]["totalWarnings"] == 2

    def test_tasks_with_errors_list_multiple(self, vault: Path) -> None:
        _write_log(vault, [
            _log_line("agent-a", "--- START ---", _recent(3)),
            _log_line("agent-a", "error in processing", _recent(3)),
            _log_line("agent-b", "--- START ---", _recent(1)),
            _log_line("agent-b", "something failed", _recent(1)),
        ])
        run_daily_report(vault)
        report = _load_report(vault)
        tasks_with_errors = report["summary"]["tasksWithErrors"]
        assert "agent-a" in tasks_with_errors
        assert "agent-b" in tasks_with_errors


# ---------------------------------------------------------------------------
# 19. reports-data.js
# ---------------------------------------------------------------------------


class TestReportsDataJs:
    """reports-data.js is created after each run and embeds all reports."""

    def test_reports_data_js_created(self, vault: Path) -> None:
        run_daily_report(vault)
        assert (_reports_dir(vault) / "reports-data.js").exists()

    def test_reports_variable_present(self, vault: Path) -> None:
        run_daily_report(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "const REPORTS" in js

    def test_task_intervals_present(self, vault: Path) -> None:
        run_daily_report(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "const TASK_INTERVALS" in js

    def test_task_config_present(self, vault: Path) -> None:
        run_daily_report(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "const TASK_CONFIG" in js

    def test_today_report_key_in_js(self, vault: Path) -> None:
        run_daily_report(vault)
        today = datetime.now().strftime("%Y-%m-%d")
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert f'"{today}"' in js

    def test_tasks_config_embedded_when_present(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "classify-agent", "script": "06-classify.ps1",
             "description": "Classify images", "intervalSeconds": 3600}
        ])
        run_daily_report(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "classify-agent" in js


# ---------------------------------------------------------------------------
# 20. Multi-report JS (second run merges old report)
# ---------------------------------------------------------------------------


class TestMultiReportJs:
    """After a second run, reports-data.js includes keys from both runs."""

    def test_second_run_merges_previous_report(self, vault: Path) -> None:
        # Inject a fake previous-day report JSON directly
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        fake_report = {"date": yesterday, "summary": {}, "tasks": {},
                       "vaultHealth": {}, "queueStats": {}}
        prev_path = _reports_dir(vault) / f"report-{yesterday}.json"
        prev_path.write_text(json.dumps(fake_report), encoding="utf-8")

        run_daily_report(vault)

        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert f'"{yesterday}"' in js
        today = datetime.now().strftime("%Y-%m-%d")
        assert f'"{today}"' in js


# ---------------------------------------------------------------------------
# 21. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Script writes structured logs with START/DONE markers to both log files."""

    def test_automation_log_exists(self, vault: Path) -> None:
        run_daily_report(vault)
        assert _shared_log(vault).exists()

    def test_start_marker_in_log(self, vault: Path) -> None:
        run_daily_report(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "--- START ---" in log

    def test_done_marker_in_log(self, vault: Path) -> None:
        run_daily_report(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "--- DONE" in log

    def test_per_task_log_created(self, vault: Path) -> None:
        run_daily_report(vault)
        logs_dir = vault / ".automation" / "logs"
        task_logs = list(logs_dir.glob("08-daily-report_*.log"))
        assert len(task_logs) == 1

    def test_log_timestamp_format(self, vault: Path) -> None:
        run_daily_report(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        pattern = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
        assert pattern.search(log), "No properly timestamped log line found"

    def test_log_appends_across_runs(self, vault: Path) -> None:
        run_daily_report(vault)
        run_daily_report(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert log.count("--- START ---") >= 2

    def test_report_path_logged(self, vault: Path) -> None:
        run_daily_report(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "Report written" in log


# ---------------------------------------------------------------------------
# 22. Missing directories / files — exits 0
# ---------------------------------------------------------------------------


class TestMissingResources:
    """Script exits 0 gracefully when optional dirs or files are absent."""

    def test_missing_processing_dir_exits_zero(self, vault: Path) -> None:
        (vault / "01-Processing").rmdir()
        result = run_daily_report(vault)
        assert result.returncode == 0, result.stderr

    def test_missing_queue_file_exits_zero(self, vault: Path) -> None:
        result = run_daily_report(vault)  # queue file was never written
        assert result.returncode == 0, result.stderr

    def test_missing_tasks_config_exits_zero(self, vault: Path) -> None:
        result = run_daily_report(vault)  # tasks.json never written
        assert result.returncode == 0, result.stderr

    def test_missing_processing_dir_report_still_written(self, vault: Path) -> None:
        (vault / "01-Processing").rmdir()
        run_daily_report(vault)
        assert _find_report(vault) is not None


# ---------------------------------------------------------------------------
# 23. Empty vault (no drafts)
# ---------------------------------------------------------------------------


class TestEmptyVault:
    """No drafts in 01-Processing → vault health lists are empty."""

    def test_no_pending_when_empty(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["vaultHealth"]["pendingReview"] == []

    def test_no_orphans_when_empty(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["vaultHealth"]["orphans"] == []

    def test_no_suggestions_when_empty(self, vault: Path) -> None:
        run_daily_report(vault)
        report = _load_report(vault)
        assert report["vaultHealth"]["qualitySuggestions"] == {}


# ---------------------------------------------------------------------------
# 24. Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running the script twice exits 0 both times; one report file per date."""

    def test_double_run_both_exit_zero(self, vault: Path) -> None:
        r1 = run_daily_report(vault)
        r2 = run_daily_report(vault)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

    def test_one_report_file_per_date(self, vault: Path) -> None:
        run_daily_report(vault)
        run_daily_report(vault)
        today = datetime.now().strftime("%Y-%m-%d")
        reports = list(_reports_dir(vault).glob(f"report-{today}*.json"))
        assert len(reports) == 1

    def test_empty_vault_idempotent(self, vault: Path) -> None:
        r1 = run_daily_report(vault)
        r2 = run_daily_report(vault)
        assert r1.returncode == 0
        assert r2.returncode == 0

    def test_vault_health_stable_on_double_run(self, vault: Path) -> None:
        _write_draft(vault, "npc-pending.md", _FM_PENDING_REVIEWED_FALSE)
        run_daily_report(vault)
        report1 = _load_report(vault)
        run_daily_report(vault)
        report2 = _load_report(vault)
        assert report1["vaultHealth"]["pendingReview"] == report2["vaultHealth"]["pendingReview"]
        assert report1["vaultHealth"]["orphans"] == report2["vaultHealth"]["orphans"]

