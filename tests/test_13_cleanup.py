"""
Tests for .automation/13-cleanup.ps1

Strategy: patch $VaultRoot in script text, write to tmp_path, invoke via subprocess.
All assertions check filesystem state (files deleted/kept, log content, JSON content).
No image processing involved — this is a log/report/metrics retention script.

Behaviors under test:
  1.  cleanupDays config      — default 90d; custom value from tasks.json
  2.  Per-task log cleanup    — *.log (not automation.log) older than cutoff deleted
  3.  Daily report cleanup    — report-*.json older than cutoff deleted
  4.  Repair report cleanup   — repair-*.json older than cutoff deleted
  5.  automation.log trimming — old lines removed; recent lines kept
  6.  agent-metrics.json trim — old runs removed per agent; recent runs kept
  7.  Vault protection        — 00-Inbox/, 01-Processing/, 02-Library/ never touched
  8.  Directory creation      — logs/ and reports/ created when missing
  9.  Logging                 — automation.log + per-task log with START/DONE markers
 10.  Idempotency             — double run exits 0 and is safe
 11.  DONE summary            — correct deleted/freed/log-lines-trimmed/metrics-trimmed
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "13-cleanup.ps1"
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"
_DEFAULT_DAYS = 90  # matches script default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _age_file(path: Path, days_old: float) -> None:
    """Set file mtime to `days_old` days in the past."""
    old_ts = time.time() - (days_old * 86400)
    os.utime(path, (old_ts, old_ts))


def _patch_script(vault_root: Path) -> str:
    """Replace hardcoded $VaultRoot with the temp path."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    return text.replace(
        f"$VaultRoot  = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot  = '{vault_root}'",
    )


def run_cleanup(
    vault_root: Path,
    cleanup_days: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Patch and execute 13-cleanup.ps1; optionally inject cleanupDays into tasks.json."""
    if cleanup_days is not None:
        tasks_json = vault_root / ".automation" / "tasks.json"
        tasks_json.write_text(json.dumps({"cleanupDays": cleanup_days}), encoding="utf-8")

    patched = _patch_script(vault_root)
    tmp_script = vault_root / "_test-13-cleanup.ps1"
    tmp_script.write_text(patched, encoding="utf-8")

    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _shared_log(vault: Path) -> Path:
    return vault / ".automation" / "logs" / "automation.log"


def _logs_dir(vault: Path) -> Path:
    return vault / ".automation" / "logs"


def _reports_dir(vault: Path) -> Path:
    return vault / ".automation" / "reports"


def _metrics_file(vault: Path) -> Path:
    return vault / ".automation" / "agent-metrics.json"


def _write_metrics(vault: Path, data: dict[str, Any]) -> None:
    _metrics_file(vault).write_text(json.dumps(data), encoding="utf-8")


def _ts(days_ago: float) -> str:
    """ISO-like timestamp `days_ago` days in the past, matching the PS1 parser."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")


def _log_line(task_id: str, msg: str, days_ago: float = 0.0) -> str:
    """Build a single log line with timestamp `days_ago` days old."""
    dt = datetime.now() - timedelta(days=days_ago)
    return f"[{dt.strftime('%Y-%m-%d %H:%M:%S')}] [{task_id}] {msg}"


def _done_line(content: str) -> str | None:
    """Extract the DONE summary line from log content."""
    return next(
        (line for line in content.splitlines() if "--- DONE" in line),
        None,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Generator[Path, None, None]:
    """Minimal vault directory tree required by 13-cleanup.ps1."""
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    (tmp_path / ".automation" / "reports").mkdir(parents=True)
    _shared_log(tmp_path).write_text("", encoding="utf-8")
    yield tmp_path


# ---------------------------------------------------------------------------
# 1. cleanupDays config
# ---------------------------------------------------------------------------


class TestCleanupDaysConfig:
    """Script reads cleanupDays from tasks.json; falls back to 90 on error/absent."""

    def test_exits_zero_with_default_days(self, vault: Path) -> None:
        result = run_cleanup(vault)
        assert result.returncode == 0, result.stderr

    def test_exits_zero_with_custom_days(self, vault: Path) -> None:
        result = run_cleanup(vault, cleanup_days=30)
        assert result.returncode == 0, result.stderr

    def test_file_within_default_window_kept(self, vault: Path) -> None:
        """File 40 days old is inside the 90d default window — not deleted."""
        log = _logs_dir(vault) / "task-x_2025-01-01.log"
        log.write_text("recent enough", encoding="utf-8")
        _age_file(log, 40)

        run_cleanup(vault)

        assert log.exists()

    def test_short_cutoff_deletes_older_file(self, vault: Path) -> None:
        """File 40 days old is deleted when cleanupDays=30."""
        log = _logs_dir(vault) / "task-y_2025-01-01.log"
        log.write_text("old log", encoding="utf-8")
        _age_file(log, 40)

        run_cleanup(vault, cleanup_days=30)

        assert not log.exists()

    def test_invalid_tasks_json_uses_default(self, vault: Path) -> None:
        """Malformed tasks.json: silently ignored; script exits 0 with default 90d."""
        (vault / ".automation" / "tasks.json").write_text("not-json{{{", encoding="utf-8")
        result = run_cleanup(vault)
        assert result.returncode == 0, result.stderr

    def test_zero_cleanup_days_uses_default(self, vault: Path) -> None:
        """cleanupDays=0 is invalid; script falls back to 90d default."""
        result = run_cleanup(vault, cleanup_days=0)
        assert result.returncode == 0, result.stderr

    def test_retention_line_logged(self, vault: Path) -> None:
        run_cleanup(vault)
        content = _shared_log(vault).read_text(encoding="utf-8")
        assert "Retention:" in content

    def test_custom_days_reflected_in_log(self, vault: Path) -> None:
        run_cleanup(vault, cleanup_days=14)
        content = _shared_log(vault).read_text(encoding="utf-8")
        assert "14d" in content


# ---------------------------------------------------------------------------
# 2. Per-task log cleanup
# ---------------------------------------------------------------------------


class TestPerTaskLogCleanup:
    """*.log files (excluding automation.log) older than cutoff are deleted."""

    def test_old_per_task_log_deleted(self, vault: Path) -> None:
        old_log = _logs_dir(vault) / "06-classify_2024-01-01.log"
        old_log.write_text("old", encoding="utf-8")
        _age_file(old_log, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        assert not old_log.exists()

    def test_recent_per_task_log_kept(self, vault: Path) -> None:
        recent_log = _logs_dir(vault) / "06-classify_2026-06-01.log"
        recent_log.write_text("recent", encoding="utf-8")
        # mtime = now; well within retention

        run_cleanup(vault)

        assert recent_log.exists()

    def test_automation_log_never_deleted(self, vault: Path) -> None:
        """automation.log must survive regardless of mtime."""
        shared = _shared_log(vault)
        _age_file(shared, _DEFAULT_DAYS + 100)

        run_cleanup(vault)

        assert shared.exists()

    def test_multiple_old_logs_all_deleted(self, vault: Path) -> None:
        logs = [
            _logs_dir(vault) / "01-cleanup_2024-01-01.log",
            _logs_dir(vault) / "02-migrate_2024-02-01.log",
            _logs_dir(vault) / "03-compile_2024-03-01.log",
        ]
        for log in logs:
            log.write_text("old", encoding="utf-8")
            _age_file(log, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        for log in logs:
            assert not log.exists(), f"{log.name} should have been deleted"

    def test_mixed_logs_correct_subset_deleted(self, vault: Path) -> None:
        old_log = _logs_dir(vault) / "task-a_2024-01-01.log"
        recent_log = _logs_dir(vault) / "task-b_2026-06-13.log"
        old_log.write_text("old", encoding="utf-8")
        recent_log.write_text("recent", encoding="utf-8")
        _age_file(old_log, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        assert not old_log.exists()
        assert recent_log.exists()

    @pytest.mark.parametrize("script_name", [
        "01-cleanup",
        "02-migrate",
        "06-classify",
        "08-daily-report",
        "12-repair-agent",
    ])
    def test_various_script_logs_deleted(self, vault: Path, script_name: str) -> None:
        log = _logs_dir(vault) / f"{script_name}_2024-01-01.log"
        log.write_text("old", encoding="utf-8")
        _age_file(log, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        assert not log.exists(), f"{log.name} should have been deleted"

    def test_logs_section_reported_in_log(self, vault: Path) -> None:
        run_cleanup(vault)
        assert "Per-task logs:" in _shared_log(vault).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. Daily report cleanup
# ---------------------------------------------------------------------------


class TestDailyReportCleanup:
    """report-*.json files older than cutoff are deleted."""

    def test_old_report_deleted(self, vault: Path) -> None:
        old_report = _reports_dir(vault) / "report-2024-01-01.json"
        old_report.write_text('{"date":"2024-01-01"}', encoding="utf-8")
        _age_file(old_report, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        assert not old_report.exists()

    def test_recent_report_kept(self, vault: Path) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        recent = _reports_dir(vault) / f"report-{today}.json"
        recent.write_text('{"date":"today"}', encoding="utf-8")

        run_cleanup(vault)

        assert recent.exists()

    def test_multiple_old_reports_all_deleted(self, vault: Path) -> None:
        reports = [
            _reports_dir(vault) / "report-2024-01-01.json",
            _reports_dir(vault) / "report-2024-03-15.json",
            _reports_dir(vault) / "report-2023-12-31.json",
        ]
        for r in reports:
            r.write_text('{"date":"old"}', encoding="utf-8")
            _age_file(r, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        for r in reports:
            assert not r.exists(), f"{r.name} should have been deleted"

    def test_non_report_json_not_deleted(self, vault: Path) -> None:
        """JSON files not matching report-*.json pattern are untouched."""
        other = _reports_dir(vault) / "other-data.json"
        other.write_text('{"keep":"me"}', encoding="utf-8")
        _age_file(other, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        assert other.exists()

    def test_daily_reports_section_in_log(self, vault: Path) -> None:
        run_cleanup(vault)
        assert "Daily reports:" in _shared_log(vault).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. Repair report cleanup
# ---------------------------------------------------------------------------


class TestRepairReportCleanup:
    """repair-*.json files older than cutoff are deleted."""

    def test_old_repair_report_deleted(self, vault: Path) -> None:
        old_repair = _reports_dir(vault) / "repair-2024-01-01.json"
        old_repair.write_text('{"type":"repair"}', encoding="utf-8")
        _age_file(old_repair, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        assert not old_repair.exists()

    def test_recent_repair_report_kept(self, vault: Path) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        recent = _reports_dir(vault) / f"repair-{today}.json"
        recent.write_text('{"type":"repair"}', encoding="utf-8")

        run_cleanup(vault)

        assert recent.exists()

    def test_multiple_old_repair_reports_deleted(self, vault: Path) -> None:
        repairs = [
            _reports_dir(vault) / "repair-2024-01-01.json",
            _reports_dir(vault) / "repair-2024-06-01.json",
        ]
        for r in repairs:
            r.write_text('{}', encoding="utf-8")
            _age_file(r, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        for r in repairs:
            assert not r.exists()

    def test_repair_and_daily_deleted_in_same_run(self, vault: Path) -> None:
        old_daily = _reports_dir(vault) / "report-2024-01-01.json"
        old_repair = _reports_dir(vault) / "repair-2024-01-01.json"
        for f in [old_daily, old_repair]:
            f.write_text('{}', encoding="utf-8")
            _age_file(f, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        assert not old_daily.exists()
        assert not old_repair.exists()

    def test_repair_reports_section_in_log(self, vault: Path) -> None:
        run_cleanup(vault)
        assert "Repair reports:" in _shared_log(vault).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. automation.log trimming
# ---------------------------------------------------------------------------


class TestAutomationLogTrimming:
    """Lines in automation.log with timestamps older than cutoff are removed."""

    def test_old_log_lines_removed(self, vault: Path) -> None:
        old_line = _log_line("classify-agent", "Processed file", days_ago=_DEFAULT_DAYS + 1)
        _shared_log(vault).write_text(old_line + "\n", encoding="utf-8")

        run_cleanup(vault)

        assert old_line not in _shared_log(vault).read_text(encoding="utf-8")

    def test_recent_log_lines_kept(self, vault: Path) -> None:
        recent_line = _log_line("classify-agent", "Processed file", days_ago=1)
        _shared_log(vault).write_text(recent_line + "\n", encoding="utf-8")

        run_cleanup(vault)

        assert recent_line in _shared_log(vault).read_text(encoding="utf-8")

    def test_mixed_lines_correct_subset_kept(self, vault: Path) -> None:
        old_line = _log_line("agent-x", "old message", days_ago=_DEFAULT_DAYS + 5)
        recent_line = _log_line("agent-y", "recent message", days_ago=1)
        _shared_log(vault).write_text(old_line + "\n" + recent_line + "\n", encoding="utf-8")

        run_cleanup(vault)

        content = _shared_log(vault).read_text(encoding="utf-8")
        assert old_line not in content
        assert recent_line in content

    def test_malformed_lines_preserved(self, vault: Path) -> None:
        """Lines without parseable timestamps are kept (safe default)."""
        malformed = "this line has no timestamp at all"
        _shared_log(vault).write_text(malformed + "\n", encoding="utf-8")

        run_cleanup(vault)

        assert malformed in _shared_log(vault).read_text(encoding="utf-8")

    def test_empty_log_no_crash(self, vault: Path) -> None:
        _shared_log(vault).write_text("", encoding="utf-8")
        result = run_cleanup(vault)
        assert result.returncode == 0, result.stderr

    def test_all_within_window_reports_no_trim(self, vault: Path) -> None:
        recent_lines = "\n".join(
            _log_line("agent", f"msg {i}", days_ago=1) for i in range(3)
        )
        _shared_log(vault).write_text(recent_lines + "\n", encoding="utf-8")

        run_cleanup(vault)

        content = _shared_log(vault).read_text(encoding="utf-8")
        assert "all lines within retention window" in content

    @pytest.mark.parametrize("days_old", [
        _DEFAULT_DAYS + 1,
        _DEFAULT_DAYS + 30,
        _DEFAULT_DAYS + 365,
    ])
    def test_various_old_ages_trimmed(self, vault: Path, days_old: float) -> None:
        old_line = _log_line("agent", "old msg", days_ago=days_old)
        _shared_log(vault).write_text(old_line + "\n", encoding="utf-8")

        run_cleanup(vault)

        assert old_line not in _shared_log(vault).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 6. agent-metrics.json trimming
# ---------------------------------------------------------------------------


class TestAgentMetricsTrimming:
    """Old runs in agent-metrics.json are removed; recent runs are preserved."""

    @staticmethod
    def _single_run_metrics(agent_id: str, days_ago: float) -> dict[str, Any]:
        return {
            agent_id: {
                "runs": [{"startedAt": _ts(days_ago), "status": "done"}]
            }
        }

    def test_old_run_removed(self, vault: Path) -> None:
        _write_metrics(vault, self._single_run_metrics("classify-agent", _DEFAULT_DAYS + 1))

        run_cleanup(vault)

        saved = json.loads(_metrics_file(vault).read_text(encoding="utf-8"))
        assert saved["classify-agent"]["runs"] == []

    def test_recent_run_kept(self, vault: Path) -> None:
        _write_metrics(vault, self._single_run_metrics("classify-agent", 1))

        run_cleanup(vault)

        saved = json.loads(_metrics_file(vault).read_text(encoding="utf-8"))
        assert len(saved["classify-agent"]["runs"]) == 1

    def test_mixed_runs_correct_subset_kept(self, vault: Path) -> None:
        data = {
            "token-agent": {
                "runs": [
                    {"startedAt": _ts(_DEFAULT_DAYS + 5), "status": "done"},
                    {"startedAt": _ts(1), "status": "done"},
                ]
            }
        }
        _write_metrics(vault, data)

        run_cleanup(vault)

        saved = json.loads(_metrics_file(vault).read_text(encoding="utf-8"))
        runs = saved["token-agent"]["runs"]
        assert len(runs) == 1
        # The kept run must be inside the retention window
        kept_dt = datetime.fromisoformat(runs[0]["startedAt"])
        cutoff = datetime.now() - timedelta(days=_DEFAULT_DAYS)
        assert kept_dt >= cutoff

    def test_multiple_agents_trimmed_independently(self, vault: Path) -> None:
        data = {
            "agent-a": {
                "runs": [
                    {"startedAt": _ts(_DEFAULT_DAYS + 10), "status": "done"},
                    {"startedAt": _ts(2), "status": "done"},
                ]
            },
            "agent-b": {
                "runs": [
                    {"startedAt": _ts(_DEFAULT_DAYS + 5), "status": "done"},
                ]
            },
        }
        _write_metrics(vault, data)

        run_cleanup(vault)

        saved = json.loads(_metrics_file(vault).read_text(encoding="utf-8"))
        assert len(saved["agent-a"]["runs"]) == 1
        assert len(saved["agent-b"]["runs"]) == 0

    def test_no_metrics_file_no_crash(self, vault: Path) -> None:
        result = run_cleanup(vault)
        assert result.returncode == 0, result.stderr

    def test_malformed_metrics_no_crash(self, vault: Path) -> None:
        _metrics_file(vault).write_text("not-json{{{{", encoding="utf-8")
        result = run_cleanup(vault)
        assert result.returncode == 0, result.stderr

    def test_all_runs_recent_count_unchanged(self, vault: Path) -> None:
        data = {
            "classify-agent": {
                "runs": [
                    {"startedAt": _ts(1), "status": "done"},
                    {"startedAt": _ts(2), "status": "done"},
                ]
            }
        }
        _write_metrics(vault, data)

        run_cleanup(vault)

        saved = json.loads(_metrics_file(vault).read_text(encoding="utf-8"))
        assert len(saved["classify-agent"]["runs"]) == 2

    def test_metrics_trimmed_in_done_summary(self, vault: Path) -> None:
        _write_metrics(vault, self._single_run_metrics("classify-agent", _DEFAULT_DAYS + 1))

        run_cleanup(vault)

        assert "metrics-trimmed=" in _shared_log(vault).read_text(encoding="utf-8")

    def test_run_with_malformed_started_at_kept(self, vault: Path) -> None:
        """Run with unparseable startedAt is preserved (safe default)."""
        data = {
            "classify-agent": {
                "runs": [{"startedAt": "not-a-date", "status": "done"}]
            }
        }
        _write_metrics(vault, data)

        run_cleanup(vault)

        saved = json.loads(_metrics_file(vault).read_text(encoding="utf-8"))
        assert len(saved["classify-agent"]["runs"]) == 1


# ---------------------------------------------------------------------------
# 7. Vault content protection
# ---------------------------------------------------------------------------


class TestVaultContentProtection:
    """00-Inbox/, 01-Processing/, and 02-Library/ must never be touched."""

    @pytest.mark.parametrize("protected_dir", [
        "00-Inbox",
        "01-Processing",
        "02-Library",
    ])
    def test_protected_dirs_untouched(self, vault: Path, protected_dir: str) -> None:
        protected = vault / protected_dir
        protected.mkdir()
        sentinel = protected / "sentinel.md"
        sentinel.write_text("protected content", encoding="utf-8")
        _age_file(sentinel, _DEFAULT_DAYS + 100)

        run_cleanup(vault)

        assert sentinel.exists(), f"File in {protected_dir}/ must not be deleted"
        assert sentinel.read_text(encoding="utf-8") == "protected content"

    def test_vault_root_markdown_untouched(self, vault: Path) -> None:
        readme = vault / "README.md"
        readme.write_text("# Vault", encoding="utf-8")
        _age_file(readme, _DEFAULT_DAYS + 100)

        run_cleanup(vault)

        assert readme.exists()


# ---------------------------------------------------------------------------
# 8. Directory creation
# ---------------------------------------------------------------------------


class TestDirectoryCreation:
    """logs/ and reports/ are auto-created when missing."""

    def test_missing_subdirs_created(self, tmp_path: Path) -> None:
        """Script creates .automation/logs/ and .automation/reports/ if absent."""
        (tmp_path / ".automation").mkdir()
        # Intentionally do NOT create logs/ or reports/

        patched = _patch_script(tmp_path)
        tmp_script = tmp_path / "_test-13-cleanup.ps1"
        tmp_script.write_text(patched, encoding="utf-8")

        result = subprocess.run(
            [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        assert (tmp_path / ".automation" / "logs").exists()
        assert (tmp_path / ".automation" / "reports").exists()

    def test_existing_dirs_no_error(self, vault: Path) -> None:
        result = run_cleanup(vault)
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 9. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Script writes START/DONE markers to both automation.log and per-task log."""

    def test_start_marker_in_shared_log(self, vault: Path) -> None:
        run_cleanup(vault)
        assert "--- START ---" in _shared_log(vault).read_text(encoding="utf-8")

    def test_done_marker_in_shared_log(self, vault: Path) -> None:
        run_cleanup(vault)
        assert "--- DONE" in _shared_log(vault).read_text(encoding="utf-8")

    def test_per_task_log_created_today(self, vault: Path) -> None:
        run_cleanup(vault)
        today = datetime.now().strftime("%Y-%m-%d")
        task_log = _logs_dir(vault) / f"13-cleanup_{today}.log"
        assert task_log.exists()

    def test_per_task_log_has_start_marker(self, vault: Path) -> None:
        run_cleanup(vault)
        today = datetime.now().strftime("%Y-%m-%d")
        task_log = _logs_dir(vault) / f"13-cleanup_{today}.log"
        assert "--- START ---" in task_log.read_text(encoding="utf-8")

    def test_log_timestamp_format(self, vault: Path) -> None:
        run_cleanup(vault)
        content = _shared_log(vault).read_text(encoding="utf-8")
        pattern = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
        assert pattern.search(content), "No properly timestamped line found in log"

    def test_task_id_in_log(self, vault: Path) -> None:
        run_cleanup(vault)
        assert "[cleanup-agent]" in _shared_log(vault).read_text(encoding="utf-8")

    def test_log_appends_across_runs(self, vault: Path) -> None:
        run_cleanup(vault)
        run_cleanup(vault)
        content = _shared_log(vault).read_text(encoding="utf-8")
        assert content.count("--- START ---") >= 2

    def test_done_line_has_all_summary_fields(self, vault: Path) -> None:
        run_cleanup(vault)
        content = _shared_log(vault).read_text(encoding="utf-8")
        assert "deleted=" in content
        assert "freed=" in content
        assert "log-lines-trimmed=" in content
        assert "metrics-trimmed=" in content


# ---------------------------------------------------------------------------
# 10. Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running the script multiple times is safe."""

    def test_double_run_both_exit_zero(self, vault: Path) -> None:
        r1 = run_cleanup(vault)
        r2 = run_cleanup(vault)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

    def test_deleted_files_stay_deleted(self, vault: Path) -> None:
        old_log = _logs_dir(vault) / "task-old_2024-01-01.log"
        old_log.write_text("old", encoding="utf-8")
        _age_file(old_log, _DEFAULT_DAYS + 1)

        run_cleanup(vault)
        assert not old_log.exists()

        run_cleanup(vault)
        assert not old_log.exists()

    def test_recent_files_survive_multiple_runs(self, vault: Path) -> None:
        recent_log = _logs_dir(vault) / "task-new_2026-06-14.log"
        recent_log.write_text("recent", encoding="utf-8")

        run_cleanup(vault)
        run_cleanup(vault)

        assert recent_log.exists()

    def test_empty_dirs_double_run_no_error(self, vault: Path) -> None:
        run_cleanup(vault)
        result = run_cleanup(vault)
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 11. DONE summary counts
# ---------------------------------------------------------------------------


class TestDoneSummary:
    """The DONE line reports correct statistics for each cleanup category."""

    def test_deleted_count_matches_files_removed(self, vault: Path) -> None:
        for i in range(3):
            log = _logs_dir(vault) / f"task-{i}_2024-01-01.log"
            log.write_text("old", encoding="utf-8")
            _age_file(log, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        content = _shared_log(vault).read_text(encoding="utf-8")
        done = _done_line(content)
        assert done is not None
        match = re.search(r"deleted=(\d+)", done)
        assert match is not None
        assert int(match.group(1)) == 3

    def test_freed_zero_when_nothing_deleted(self, vault: Path) -> None:
        run_cleanup(vault)
        content = _shared_log(vault).read_text(encoding="utf-8")
        done = _done_line(content)
        assert done is not None
        assert "freed=0MB" in done

    def test_log_lines_trimmed_count_correct(self, vault: Path) -> None:
        # 5 old lines + 2 recent lines pre-written
        lines = (
            [_log_line("agent", f"old {i}", days_ago=_DEFAULT_DAYS + 1) for i in range(5)]
            + [_log_line("agent", f"new {i}", days_ago=1) for i in range(2)]
        )
        _shared_log(vault).write_text("\n".join(lines) + "\n", encoding="utf-8")

        run_cleanup(vault)

        content = _shared_log(vault).read_text(encoding="utf-8")
        done = _done_line(content)
        assert done is not None
        match = re.search(r"log-lines-trimmed=(\d+)", done)
        assert match is not None
        assert int(match.group(1)) == 5

    def test_metrics_trimmed_count_correct(self, vault: Path) -> None:
        data = {
            "agent-a": {
                "runs": [
                    {"startedAt": _ts(_DEFAULT_DAYS + 1), "status": "done"},
                    {"startedAt": _ts(_DEFAULT_DAYS + 2), "status": "done"},
                    {"startedAt": _ts(1), "status": "done"},
                ]
            }
        }
        _write_metrics(vault, data)

        run_cleanup(vault)

        content = _shared_log(vault).read_text(encoding="utf-8")
        done = _done_line(content)
        assert done is not None
        match = re.search(r"metrics-trimmed=(\d+)", done)
        assert match is not None
        assert int(match.group(1)) == 2

    def test_deleted_combines_all_categories(self, vault: Path) -> None:
        """deleted= counts per-task logs + daily reports + repair reports together."""
        old_log = _logs_dir(vault) / "task-x_2024-01-01.log"
        old_daily = _reports_dir(vault) / "report-2024-01-01.json"
        old_repair = _reports_dir(vault) / "repair-2024-01-01.json"
        for f in [old_log, old_daily, old_repair]:
            f.write_text("old", encoding="utf-8")
            _age_file(f, _DEFAULT_DAYS + 1)

        run_cleanup(vault)

        content = _shared_log(vault).read_text(encoding="utf-8")
        done = _done_line(content)
        assert done is not None
        match = re.search(r"deleted=(\d+)", done)
        assert match is not None
        assert int(match.group(1)) == 3

