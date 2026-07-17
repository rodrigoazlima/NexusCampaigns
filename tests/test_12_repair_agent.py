"""
Tests for .automation/12-repair-agent.ps1 - Repair Agent

Strategy: patch $VaultRoot in the script text, inject stubs for external
calls (Invoke-WebRequest for LM Studio), write the patched copy to tmp_path,
and invoke via subprocess.  All assertions check filesystem state and JSON.

No LM Studio, no Python subprocess, no network access needed.

Behaviors under test:
  1.  Integration         - full script exits 0; START/DONE markers; log files
  2.  Stale lock repair   - runner.lock >30 min removed; fresh lock preserved
  3.  Missing directories - required dirs created when absent
  4.  State entry repair  - missing tasks-state.json entries added with epoch ts
  5.  Stale agent detect  - agents overdue >2x interval → WARN logged
  6.  Dashboard integrity - reports-data.js rebuilt when missing/stale/outdated
  7.  Error log parsing   - keywords parsed; patterns → buckets; 24h cutoff; self-ref skipped
  8.  Bad-index feedback  - improvement notes added; short_content threshold warns
  9.  SHA256 identity     - flags md files missing/unresolvable sha256; clears false positives
 10.  Repair report       - writes reports/repair-YYYY-MM-DD.json with correct structure
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

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "12-repair-agent.ps1"
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

# Anchor used to inject stubs just before the main execution block
_MAIN_ANCHOR = "Write-Log '--- START ---'"


# ---------------------------------------------------------------------------
# Image comparison helpers (project convention)
# ---------------------------------------------------------------------------


def images_are_equal(a: Path, b: Path) -> bool:
    """True when two image files have byte-identical content."""
    return a.read_bytes() == b.read_bytes()


def assert_images_similar(a: Path, b: Path, min_ssim: float = 0.90) -> None:
    """Assert SSIM >= min_ssim between two image files; skipped if skimage absent."""
    try:
        import numpy as np
        from PIL import Image
        from skimage.metrics import structural_similarity as ssim  # type: ignore
    except ImportError:
        pytest.skip("scikit-image / Pillow not installed")
    arr_a = np.array(Image.open(a).convert("L"))
    arr_b = np.array(Image.open(b).convert("L"))
    score = float(ssim(arr_a, arr_b))
    assert score >= min_ssim, f"SSIM {score:.3f} < {min_ssim}: {a.name} vs {b.name}"


# ---------------------------------------------------------------------------
# Script patching helpers
# ---------------------------------------------------------------------------

# Overrides Invoke-WebRequest so the LM Studio check fails fast (no network)
_STUB_LM_STUDIO = (
    "function Invoke-WebRequest {"
    " param([string]$Uri, [int]$TimeoutSec, [switch]$UseBasicParsing, $ErrorAction)"
    " throw 'LM Studio: stubbed in test' }"
)


def _patch_script(vault_root: Path, extra_stubs: str = "") -> str:
    """Replace $VaultRoot; inject stubs before the main execution block."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    # Note: 2 spaces before '=' in the original script
    text = text.replace(
        f"$VaultRoot  = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot  = '{vault_root}'",
    )
    stubs = _STUB_LM_STUDIO
    if extra_stubs:
        stubs = stubs + "\n" + extra_stubs
    text = text.replace(_MAIN_ANCHOR, stubs + "\n" + _MAIN_ANCHOR)
    return text


def _run_script(
    vault_root: Path,
    extra_stubs: str = "",
    timeout: int = 90,
) -> "subprocess.CompletedProcess[str]":
    """Patch and execute the repair agent; return CompletedProcess."""
    patched = _patch_script(vault_root, extra_stubs=extra_stubs)
    tmp_script = vault_root / "_test-12-repair-agent.ps1"
    tmp_script.write_text(patched, encoding="utf-8")
    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Path & data helpers
# ---------------------------------------------------------------------------


def _auto_dir(vault: Path) -> Path:
    return vault / ".automation"


def _shared_log(vault: Path) -> Path:
    return vault / ".automation" / "logs" / "automation.log"


def _reports_dir(vault: Path) -> Path:
    return vault / ".automation" / "reports"


def _lock_file(vault: Path) -> Path:
    return vault / ".automation" / "runner.lock"


def _tasks_conf(vault: Path) -> Path:
    return vault / ".automation" / "tasks.json"


def _state_file(vault: Path) -> Path:
    return vault / ".automation" / "tasks-state.json"


def _bad_index_path(vault: Path) -> Path:
    return vault / ".automation" / "bad-index.json"


def _processed_images_path(vault: Path) -> Path:
    return vault / ".automation" / "processed-images.json"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _find_repair_report(vault: Path) -> Path | None:
    candidate = _reports_dir(vault) / f"repair-{_today()}.json"
    return candidate if candidate.exists() else None


def _load_repair_report(vault: Path) -> dict:
    path = _find_repair_report(vault)
    assert path is not None, "Repair report not found"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_tasks_config(vault: Path, tasks: list[dict]) -> None:
    _tasks_conf(vault).write_text(json.dumps({"tasks": tasks}), encoding="utf-8")


def _write_state(vault: Path, state: dict) -> None:
    _state_file(vault).write_text(json.dumps(state), encoding="utf-8")


def _write_log_lines(vault: Path, lines: list[str]) -> None:
    _shared_log(vault).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _log_line(task_id: str, msg: str, dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return f"[{_fmt_ts(dt)}] [{task_id}] {msg}"


def _recent(hours_ago: float = 1.0) -> datetime:
    return datetime.now() - timedelta(hours=hours_ago)


def _old(hours_ago: float = 26.0) -> datetime:
    return datetime.now() - timedelta(hours=hours_ago)


def _make_processing_md(
    vault: Path,
    filename: str,
    sha256: str = "",
) -> Path:
    """Write a .md file to 01-Processing/ with optional sha256 in frontmatter."""
    proc_dir = vault / "01-Processing"
    proc_dir.mkdir(parents=True, exist_ok=True)
    sha_line = f"sha256: {sha256}\n" if sha256 else ""
    content = (
        f"---\n{sha_line}id: test-entity\ntype: npc\nstatus: draft\n---\n"
        "Body content here.\n"
    )
    p = proc_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


def _make_processed_images(vault: Path, sha256_list: list[str]) -> None:
    """Write a v2 processed-images.json index with the given sha256 hashes."""
    images = {sha: {"filename": f"test-{sha[:8]}.png"} for sha in sha256_list}
    _processed_images_path(vault).write_text(
        json.dumps({"version": 2, "images": images}), encoding="utf-8"
    )


def _fake_sha256(seed: int = 0) -> str:
    """Return a valid-length (64 hex char) deterministic fake SHA256."""
    return format(seed, "064x")


def _age_file(path: Path, age_minutes: float) -> None:
    """Set a file's mtime to simulate the given age in minutes."""
    mtime = time.time() - (age_minutes * 60)
    os.utime(path, (mtime, mtime))


def _write_bad_index(vault: Path, entries: list[dict]) -> None:
    data = {"version": 1, "entries": entries}
    _bad_index_path(vault).write_text(json.dumps(data), encoding="utf-8")


def _default_bad_entry(filename: str, reason: str = "short_content") -> dict:
    return {
        "filename": filename,
        "sha256": "",
        "reason": reason,
        "flagged_at": "2026-06-14T10:00:00",
        "reprocessing_steps": ["vision-agent"],
        "improvements": [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal vault tree for 12-repair-agent.ps1."""
    auto = tmp_path / ".automation"
    (auto / "logs").mkdir(parents=True)
    (auto / "reports").mkdir(parents=True)
    (tmp_path / "00-Inbox" / "images").mkdir(parents=True)
    (tmp_path / "01-Processing").mkdir(parents=True)
    (tmp_path / "02-Library").mkdir(parents=True)
    # Empty shared log so Get-Content doesn't fail
    _shared_log(tmp_path).write_text("", encoding="utf-8")
    # Minimal tasks config with a recent lastRun (not stale)
    recent_ts = (datetime.now() - timedelta(minutes=30)).isoformat()
    _write_tasks_config(tmp_path, [
        {
            "id": "classify-agent",
            "script": "06-classify.ps1",
            "description": "Classify images",
            "intervalSeconds": 3600,
        },
    ])
    _write_state(tmp_path, {"classify-agent": {"lastRun": recent_ts}})
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    """Full script run exits 0 and produces expected log artefacts."""

    def test_exits_zero(self, vault: Path) -> None:
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    def test_log_has_start_marker(self, vault: Path) -> None:
        _run_script(vault)
        assert "--- START ---" in _shared_log(vault).read_text(encoding="utf-8")

    def test_log_has_done_marker(self, vault: Path) -> None:
        _run_script(vault)
        assert "--- DONE" in _shared_log(vault).read_text(encoding="utf-8")

    def test_log_has_task_id_prefix(self, vault: Path) -> None:
        _run_script(vault)
        assert "[repair-agent]" in _shared_log(vault).read_text(encoding="utf-8")

    def test_per_task_log_created(self, vault: Path) -> None:
        _run_script(vault)
        task_logs = list((_auto_dir(vault) / "logs").glob("12-repair-agent_*.log"))
        assert len(task_logs) >= 1

    def test_repair_report_created(self, vault: Path) -> None:
        _run_script(vault)
        assert _find_repair_report(vault) is not None

    def test_second_run_exits_zero(self, vault: Path) -> None:
        _run_script(vault)
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    def test_log_appends_across_runs(self, vault: Path) -> None:
        _run_script(vault)
        _run_script(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert log.count("--- START ---") >= 2

    def test_log_timestamp_format(self, vault: Path) -> None:
        _run_script(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", log)


# ---------------------------------------------------------------------------
# 2. Stale lock repair
# ---------------------------------------------------------------------------


class TestStaleLockRepair:
    """runner.lock older than 30 min is removed; fresh lock is left alone."""

    def test_stale_lock_removed(self, vault: Path) -> None:
        lock = _lock_file(vault)
        lock.write_text("locked", encoding="utf-8")
        _age_file(lock, age_minutes=45)
        _run_script(vault)
        assert not lock.exists(), "Stale lock (45 min) must be removed"

    def test_stale_lock_repair_logged(self, vault: Path) -> None:
        lock = _lock_file(vault)
        lock.write_text("locked", encoding="utf-8")
        _age_file(lock, age_minutes=45)
        _run_script(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "stale" in log.lower() or "runner.lock" in log.lower()

    def test_stale_lock_in_repair_report(self, vault: Path) -> None:
        lock = _lock_file(vault)
        lock.write_text("locked", encoding="utf-8")
        _age_file(lock, age_minutes=45)
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any(
            "runner.lock" in r.lower() or "stale" in r.lower()
            for r in report["repairs"]
        )

    def test_fresh_lock_preserved(self, vault: Path) -> None:
        lock = _lock_file(vault)
        lock.write_text("locked", encoding="utf-8")
        _age_file(lock, age_minutes=5)
        _run_script(vault)
        assert lock.exists(), "Fresh lock (5 min) must NOT be removed"

    def test_no_lock_exits_zero(self, vault: Path) -> None:
        assert not _lock_file(vault).exists()
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    def test_no_lock_ok_logged(self, vault: Path) -> None:
        _run_script(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "runner.lock" in log

    @pytest.mark.parametrize("age_minutes", [31, 60, 120, 1440])
    def test_various_stale_ages_removed(self, vault: Path, age_minutes: float) -> None:
        lock = _lock_file(vault)
        lock.write_text("locked", encoding="utf-8")
        _age_file(lock, age_minutes=age_minutes)
        _run_script(vault)
        assert not lock.exists(), f"Lock aged {age_minutes} min must be removed"


# ---------------------------------------------------------------------------
# 3. Missing directory repair
# ---------------------------------------------------------------------------


class TestMissingDirectories:
    """All required directories are created when absent."""

    def test_missing_logs_dir_created(self, vault: Path) -> None:
        logs = _auto_dir(vault) / "logs"
        shutil.rmtree(logs)
        _run_script(vault)
        assert logs.exists()

    def test_missing_reports_dir_created(self, vault: Path) -> None:
        shutil.rmtree(_reports_dir(vault))
        _run_script(vault)
        assert _reports_dir(vault).exists()

    def test_missing_inbox_images_created(self, vault: Path) -> None:
        inbox_img = vault / "00-Inbox" / "images"
        shutil.rmtree(inbox_img)
        _run_script(vault)
        assert inbox_img.exists()

    def test_missing_processing_dir_created(self, vault: Path) -> None:
        shutil.rmtree(vault / "01-Processing")
        _run_script(vault)
        assert (vault / "01-Processing").exists()

    def test_existing_dir_contents_preserved(self, vault: Path) -> None:
        sentinel = vault / "01-Processing" / "sentinel.txt"
        sentinel.write_text("keep me", encoding="utf-8")
        _run_script(vault)
        assert sentinel.read_text(encoding="utf-8") == "keep me"

    def test_exits_zero_with_multiple_missing_dirs(self, vault: Path) -> None:
        shutil.rmtree(vault / "01-Processing")
        shutil.rmtree(_reports_dir(vault))
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    def test_created_dir_in_repair_report(self, vault: Path) -> None:
        shutil.rmtree(vault / "01-Processing")
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any(
            "01-Processing" in r or "directory" in r.lower()
            for r in report["repairs"]
        )


# ---------------------------------------------------------------------------
# 4. tasks-state.json missing entry repair
# ---------------------------------------------------------------------------


class TestTasksStateMissingEntries:
    """Missing entries in tasks-state.json are added with epoch timestamps."""

    def test_missing_entry_added(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "new-task", "script": "99.ps1",
             "description": "New task", "intervalSeconds": 3600},
        ])
        _write_state(vault, {})
        _run_script(vault)
        state = json.loads(_state_file(vault).read_text(encoding="utf-8"))
        assert "new-task" in state

    def test_epoch_timestamp_written(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "fresh-task", "script": "99.ps1",
             "description": "Fresh", "intervalSeconds": 3600},
        ])
        _write_state(vault, {})
        _run_script(vault)
        state = json.loads(_state_file(vault).read_text(encoding="utf-8"))
        assert state["fresh-task"]["lastRun"].startswith("1970-01-01")

    def test_existing_entry_not_overwritten(self, vault: Path) -> None:
        ts = "2026-06-14T10:00:00.0000000-00:00"
        _write_tasks_config(vault, [
            {"id": "classify-agent", "script": "06.ps1",
             "description": "Classify", "intervalSeconds": 3600},
        ])
        _write_state(vault, {"classify-agent": {"lastRun": ts}})
        _run_script(vault)
        state = json.loads(_state_file(vault).read_text(encoding="utf-8"))
        assert state["classify-agent"]["lastRun"] == ts

    def test_multiple_missing_entries_all_added(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "task-a", "script": "01.ps1", "description": "A", "intervalSeconds": 3600},
            {"id": "task-b", "script": "02.ps1", "description": "B", "intervalSeconds": 3600},
            {"id": "task-c", "script": "03.ps1", "description": "C", "intervalSeconds": 3600},
        ])
        _write_state(vault, {})
        _run_script(vault)
        state = json.loads(_state_file(vault).read_text(encoding="utf-8"))
        for tid in ("task-a", "task-b", "task-c"):
            assert tid in state, f"Missing state entry for {tid!r}"

    def test_idempotent_second_run_valid_json(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "idempotent-task", "script": "01.ps1",
             "description": "X", "intervalSeconds": 3600},
        ])
        _write_state(vault, {})
        _run_script(vault)
        _run_script(vault)
        # Must be valid JSON with the entry present
        state = json.loads(_state_file(vault).read_text(encoding="utf-8"))
        assert "idempotent-task" in state

    def test_repair_entry_in_report(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "missing-entry-task", "script": "99.ps1",
             "description": "Missing", "intervalSeconds": 3600},
        ])
        _write_state(vault, {})
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any("missing-entry-task" in r for r in report["repairs"])


# ---------------------------------------------------------------------------
# 5. Stale agent detection
# ---------------------------------------------------------------------------


class TestStaleAgentDetection:
    """Agents overdue by >2x their interval are logged as WARN."""

    def test_overdue_agent_warn_in_log(self, vault: Path) -> None:
        ts = (datetime.now() - timedelta(hours=10)).isoformat()
        _write_tasks_config(vault, [
            {"id": "slow-agent", "script": "99.ps1",
             "description": "Slow", "intervalSeconds": 3600},
        ])
        _write_state(vault, {"slow-agent": {"lastRun": ts}})
        _run_script(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "slow-agent" in log and ("overdue" in log.lower() or "[WARN]" in log)

    def test_overdue_agent_in_report_warnings(self, vault: Path) -> None:
        ts = (datetime.now() - timedelta(hours=10)).isoformat()
        _write_tasks_config(vault, [
            {"id": "warn-task", "script": "99.ps1",
             "description": "Warn", "intervalSeconds": 3600},
        ])
        _write_state(vault, {"warn-task": {"lastRun": ts}})
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any("warn-task" in w for w in report["warnings"])

    def test_fresh_agent_not_in_warnings(self, vault: Path) -> None:
        # 30 min ago, 1-hour interval → NOT overdue (elapsed < 2x interval)
        ts = (datetime.now() - timedelta(minutes=30)).isoformat()
        _write_tasks_config(vault, [
            {"id": "fresh-agent", "script": "99.ps1",
             "description": "Fresh", "intervalSeconds": 3600},
        ])
        _write_state(vault, {"fresh-agent": {"lastRun": ts}})
        _run_script(vault)
        report = _load_repair_report(vault)
        assert not any(
            "fresh-agent" in w and "overdue" in w.lower()
            for w in report["warnings"]
        )

    def test_epoch_lastrun_always_overdue(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "never-ran-agent", "script": "99.ps1",
             "description": "Never ran", "intervalSeconds": 3600},
        ])
        _write_state(vault, {
            "never-ran-agent": {"lastRun": "1970-01-01T00:00:00.0000000-00:00"},
        })
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any("never-ran-agent" in w for w in report["warnings"])

    @pytest.mark.parametrize("elapsed_hours,interval_hours,expect_warn", [
        (3.0, 1, True),   # 3x interval → overdue
        (2.5, 1, True),   # 2.5x interval → overdue
        (1.5, 1, False),  # 1.5x interval < 2x threshold → not overdue
        (0.5, 1, False),  # 0.5x interval → not overdue
    ])
    def test_overdue_threshold_parametrized(
        self,
        vault: Path,
        elapsed_hours: float,
        interval_hours: float,
        expect_warn: bool,
    ) -> None:
        ts = (datetime.now() - timedelta(hours=elapsed_hours)).isoformat()
        interval_sec = int(interval_hours * 3600)
        _write_tasks_config(vault, [
            {"id": "threshold-agent", "script": "99.ps1",
             "description": "Threshold test", "intervalSeconds": interval_sec},
        ])
        _write_state(vault, {"threshold-agent": {"lastRun": ts}})
        _run_script(vault)
        report = _load_repair_report(vault)
        warned = any("threshold-agent" in w for w in report["warnings"])
        assert warned == expect_warn, (
            f"elapsed={elapsed_hours}h interval={interval_hours}h: "
            f"expected warn={expect_warn}, got {warned}"
        )


# ---------------------------------------------------------------------------
# 6. Dashboard integrity (reports-data.js)
# ---------------------------------------------------------------------------


class TestDashboardIntegrity:
    """reports-data.js is rebuilt when missing, stale, or outdated."""

    def test_missing_js_rebuilt_on_first_run(self, vault: Path) -> None:
        _run_script(vault)
        assert (_reports_dir(vault) / "reports-data.js").exists()

    def test_rebuilt_js_has_task_config(self, vault: Path) -> None:
        _run_script(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "TASK_CONFIG" in js

    def test_rebuilt_js_has_task_intervals(self, vault: Path) -> None:
        _run_script(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "TASK_INTERVALS" in js

    def test_rebuilt_js_has_reports_var(self, vault: Path) -> None:
        _run_script(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "REPORTS" in js

    def test_stale_js_more_than_2h_rebuilt(self, vault: Path) -> None:
        js_path = _reports_dir(vault) / "reports-data.js"
        js_path.write_text("const REPORTS = {};", encoding="utf-8")
        _age_file(js_path, age_minutes=130)  # 2h10m > 2h threshold
        _run_script(vault)
        js = js_path.read_text(encoding="utf-8")
        assert "TASK_CONFIG" in js

    def test_js_missing_today_date_triggers_rebuild(self, vault: Path) -> None:
        js_path = _reports_dir(vault) / "reports-data.js"
        # Write JS without today's date; mtime is fresh (< 2h)
        js_path.write_text("const REPORTS = {};", encoding="utf-8")
        _run_script(vault)
        js = js_path.read_text(encoding="utf-8")
        # Rebuilt: must have full JS structure
        assert "TASK_CONFIG" in js and "TASK_INTERVALS" in js

    def test_js_embeds_task_id(self, vault: Path) -> None:
        _write_tasks_config(vault, [
            {"id": "my-special-agent", "script": "06.ps1",
             "description": "Special", "intervalSeconds": 3600},
        ])
        _write_state(vault, {"my-special-agent": {
            "lastRun": (datetime.now() - timedelta(minutes=30)).isoformat(),
        }})
        _run_script(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert "my-special-agent" in js

    def test_existing_report_json_embedded_in_js(self, vault: Path) -> None:
        today = _today()
        report_data = {"date": today, "summary": {}, "tasks": {}}
        (_reports_dir(vault) / f"report-{today}.json").write_text(
            json.dumps(report_data), encoding="utf-8"
        )
        _run_script(vault)
        js = (_reports_dir(vault) / "reports-data.js").read_text(encoding="utf-8")
        assert today in js

    def test_rebuild_noted_in_repair_report(self, vault: Path) -> None:
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any("reports-data" in r.lower() for r in report["repairs"])


# ---------------------------------------------------------------------------
# 7. Error log parsing & bucket classification
# ---------------------------------------------------------------------------


class TestErrorLogParsing:
    """Error lines are parsed from the last 24h and classified into buckets."""

    @pytest.mark.parametrize("keyword", [
        "error", "failed", "exception", "critical",
        "Error", "FAILED", "EXCEPTION", "Critical",
    ])
    def test_error_keywords_trigger_parsing(self, vault: Path, keyword: str) -> None:
        _write_log_lines(vault, [
            _log_line("parse-agent", f"Something {keyword} occurred", _recent(1)),
        ])
        _run_script(vault)
        report = _load_repair_report(vault)
        task_errors = report.get("taskErrors") or {}
        assert "parse-agent" in task_errors

    @pytest.mark.parametrize("msg,expected_bucket", [
        ("stale lock file detected",     "stale-lock"),
        ("runner.lock is present",       "stale-lock"),
        ("lock file older than 30 min",  "stale-lock"),
        ("directory not found error",    "missing-directory"),
        ("cannot find path C:\\temp",    "missing-directory"),
        ("reports-data.js error",        "stale-dashboard"),
        ("connection refused by host",   "connection-refused"),
        ("operation timed out",          "timeout"),
        ("access denied to resource",    "access-denied"),
        ("lm studio offline now",        "lm-studio-offline"),
    ])
    def test_known_pattern_bucket(
        self, vault: Path, msg: str, expected_bucket: str
    ) -> None:
        _write_log_lines(vault, [
            _log_line("test-agent", f"error: {msg}", _recent(1)),
        ])
        _run_script(vault)
        report = _load_repair_report(vault)
        buckets = report.get("errorBuckets") or {}
        assert expected_bucket in buckets, (
            f"Expected bucket '{expected_bucket}' for {msg!r}. "
            f"Got: {list(buckets.keys())}"
        )

    def test_unrecognized_pattern_lands_in_unknown(self, vault: Path) -> None:
        _write_log_lines(vault, [
            _log_line("mystery-agent", "completely unknown fatal error xyz", _recent(1)),
        ])
        _run_script(vault)
        report = _load_repair_report(vault)
        buckets = report.get("errorBuckets") or {}
        assert "unknown" in buckets

    def test_old_entries_excluded_from_parsing(self, vault: Path) -> None:
        _write_log_lines(vault, [
            _log_line("old-agent", "old critical failure", _old(30)),
        ])
        _run_script(vault)
        report = _load_repair_report(vault)
        task_errors = report.get("taskErrors") or {}
        assert "old-agent" not in task_errors

    def test_recent_entries_included_in_parsing(self, vault: Path) -> None:
        _write_log_lines(vault, [
            _log_line("new-agent", "critical error in processing", _recent(1)),
        ])
        _run_script(vault)
        report = _load_repair_report(vault)
        task_errors = report.get("taskErrors") or {}
        assert "new-agent" in task_errors

    def test_self_referential_check_lines_skipped(self, vault: Path) -> None:
        _write_log_lines(vault, [
            _log_line("repair-agent", "[CHECK] validation error detected", _recent(1)),
            _log_line("repair-agent", "[WARN] error count is high", _recent(1)),
            _log_line("repair-agent", "[REPAIR] fixing error state", _recent(1)),
            _log_line("repair-agent", "Error buckets: {timeout=1}", _recent(1)),
        ])
        _run_script(vault)
        report = _load_repair_report(vault)
        task_errors = report.get("taskErrors") or {}
        assert "repair-agent" not in task_errors

    def test_start_done_markers_not_parsed_as_errors(self, vault: Path) -> None:
        _write_log_lines(vault, [
            _log_line("task-x", "--- START ---", _recent(2)),
            _log_line("task-x", "--- DONE ---", _recent(2)),
        ])
        _run_script(vault)
        report = _load_repair_report(vault)
        task_errors = report.get("taskErrors") or {}
        assert "task-x" not in task_errors

    def test_malformed_log_lines_no_crash(self, vault: Path) -> None:
        _write_log_lines(vault, [
            "not a valid log line at all",
            "[bad-ts] [task] msg",
            "   ",
            _log_line("good-agent", "--- START ---", _recent(1)),
        ])
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 8. bad-index.json feedback loop
# ---------------------------------------------------------------------------


class TestBadIndexFeedback:
    """Repair agent annotates bad-index.json entries with improvement notes."""

    def test_improvement_note_added_to_entry(self, vault: Path) -> None:
        _write_bad_index(vault, [_default_bad_entry("npc-bad.md")])
        _run_script(vault)
        data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
        entry = data["entries"][0]
        assert entry.get("improvements") and len(entry["improvements"]) > 0

    def test_existing_improvement_not_duplicated(self, vault: Path) -> None:
        entry = _default_bad_entry("npc-has-note.md")
        entry["improvements"] = ["repair-agent checked 2026-06-13: prior note"]
        _write_bad_index(vault, [entry])
        _run_script(vault)
        data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
        assert len(data["entries"][0]["improvements"]) == 1

    def test_short_content_above_threshold_warns(self, vault: Path) -> None:
        # >10 short_content entries triggers WARN
        entries = [_default_bad_entry(f"npc-{i}.md") for i in range(12)]
        _write_bad_index(vault, entries)
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any("short_content" in w for w in report["warnings"])

    def test_short_content_below_threshold_no_warn(self, vault: Path) -> None:
        entries = [_default_bad_entry(f"npc-{i}.md") for i in range(5)]
        _write_bad_index(vault, entries)
        _run_script(vault)
        report = _load_repair_report(vault)
        assert not any("short_content" in w for w in report["warnings"])

    def test_absent_bad_index_no_crash(self, vault: Path) -> None:
        assert not _bad_index_path(vault).exists()
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    def test_empty_bad_index_no_crash(self, vault: Path) -> None:
        _write_bad_index(vault, [])
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    def test_update_reflected_in_repair_report(self, vault: Path) -> None:
        _write_bad_index(vault, [_default_bad_entry("npc-update.md")])
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any("bad-index" in r.lower() for r in report["repairs"])

    def test_reason_groups_logged(self, vault: Path) -> None:
        entries = [
            {**_default_bad_entry(f"npc-short-{i}.md"), "reason": "short_content"}
            for i in range(3)
        ] + [
            {**_default_bad_entry("npc-other.md"), "reason": "other_reason"}
        ]
        _write_bad_index(vault, entries)
        _run_script(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "short_content" in log


# ---------------------------------------------------------------------------
# 9. SHA256 identity check
# ---------------------------------------------------------------------------


class TestSha256IdentityCheck:
    """01-Processing md files are flagged when SHA256 is missing or unresolvable."""

    def test_no_sha256_in_frontmatter_flagged(self, vault: Path) -> None:
        _make_processing_md(vault, "npc-no-sha.md", sha256="")
        _make_processed_images(vault, [])
        _run_script(vault)
        data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
        filenames = [e["filename"] for e in data["entries"]]
        assert "npc-no-sha.md" in filenames

    def test_unresolvable_sha256_flagged(self, vault: Path) -> None:
        unknown_sha = _fake_sha256(999)
        _make_processing_md(vault, "npc-bad-sha.md", sha256=unknown_sha)
        _make_processed_images(vault, [_fake_sha256(1)])
        _run_script(vault)
        data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
        filenames = [e["filename"] for e in data["entries"]]
        assert "npc-bad-sha.md" in filenames

    def test_valid_sha256_not_flagged(self, vault: Path) -> None:
        sha = _fake_sha256(42)
        _make_processing_md(vault, "npc-good-sha.md", sha256=sha)
        _make_processed_images(vault, [sha])
        _run_script(vault)
        if _bad_index_path(vault).exists():
            data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
            flagged = [
                e["filename"] for e in data["entries"]
                if e.get("reason") == "missing_image_ref"
            ]
            assert "npc-good-sha.md" not in flagged

    def test_already_flagged_file_not_duplicated(self, vault: Path) -> None:
        _make_processing_md(vault, "npc-dup.md", sha256="")
        _write_bad_index(vault, [{
            "filename": "npc-dup.md",
            "sha256": "",
            "reason": "missing_image_ref",
            "flagged_at": "2026-06-14T09:00:00",
            "reprocessing_steps": [],
            "improvements": [],
        }])
        _run_script(vault)
        data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
        count = sum(1 for e in data["entries"] if e["filename"] == "npc-dup.md")
        assert count == 1, "File must not be flagged twice"

    def test_false_positive_cleared_when_sha_resolves(self, vault: Path) -> None:
        sha = _fake_sha256(77)
        _make_processing_md(vault, "npc-resolved.md", sha256=sha)
        # Pre-flag the file as missing_image_ref
        _write_bad_index(vault, [{
            "filename": "npc-resolved.md",
            "sha256": sha,
            "reason": "missing_image_ref",
            "flagged_at": "2026-06-14T09:00:00",
            "reprocessing_steps": [],
            "improvements": [],
        }])
        # Now register the sha in the index → should clear the flag
        _make_processed_images(vault, [sha])
        _run_script(vault)
        data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
        remaining = [
            e["filename"] for e in data["entries"]
            if e["reason"] == "missing_image_ref"
        ]
        assert "npc-resolved.md" not in remaining

    def test_cleared_false_positive_in_repair_report(self, vault: Path) -> None:
        sha = _fake_sha256(88)
        _make_processing_md(vault, "npc-cleared.md", sha256=sha)
        _write_bad_index(vault, [{
            "filename": "npc-cleared.md",
            "sha256": sha,
            "reason": "missing_image_ref",
            "flagged_at": "2026-06-14T09:00:00",
            "reprocessing_steps": [],
            "improvements": [],
        }])
        _make_processed_images(vault, [sha])
        _run_script(vault)
        report = _load_repair_report(vault)
        assert any("cleared" in r.lower() or "false" in r.lower() or "stale" in r.lower()
                   for r in report["repairs"])

    def test_index_readme_files_skipped(self, vault: Path) -> None:
        _make_processing_md(vault, "index.md", sha256="")
        _make_processing_md(vault, "README.md", sha256="")
        _run_script(vault)
        if _bad_index_path(vault).exists():
            data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
            flagged = [
                e["filename"] for e in data["entries"]
                if e.get("reason") == "missing_image_ref"
            ]
            assert "index.md" not in flagged
            assert "README.md" not in flagged

    def test_missing_processed_images_json_no_crash(self, vault: Path) -> None:
        _make_processing_md(vault, "npc-any.md", sha256=_fake_sha256(1))
        assert not _processed_images_path(vault).exists()
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    def test_empty_processing_dir_no_crash(self, vault: Path) -> None:
        assert list((vault / "01-Processing").iterdir()) == []
        result = _run_script(vault)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("sha_length,should_flag", [
        (63, True),   # too short - invalid length
        (65, True),   # too long - invalid length
        (64, False),  # correct - resolves in index
    ])
    def test_sha256_length_validation(
        self, vault: Path, sha_length: int, should_flag: bool
    ) -> None:
        sha = "a" * sha_length
        _make_processing_md(vault, "npc-len-test.md", sha256=sha)
        _make_processed_images(vault, ["a" * 64])  # index has the 64-char version
        _run_script(vault)
        if _bad_index_path(vault).exists():
            data = json.loads(_bad_index_path(vault).read_text(encoding="utf-8"))
            flagged = any(
                e["filename"] == "npc-len-test.md"
                and e.get("reason") == "missing_image_ref"
                for e in data["entries"]
            )
        else:
            flagged = False
        assert flagged == should_flag, (
            f"sha_length={sha_length}: expected flagged={should_flag}, got {flagged}"
        )


# ---------------------------------------------------------------------------
# 10. Repair report structure
# ---------------------------------------------------------------------------


class TestRepairReport:
    """Repair report JSON has the expected structure and all required keys."""

    def test_report_written_to_reports_dir(self, vault: Path) -> None:
        _run_script(vault)
        assert (_reports_dir(vault) / f"repair-{_today()}.json").exists()

    def test_report_is_valid_json(self, vault: Path) -> None:
        _run_script(vault)
        path = _find_repair_report(vault)
        assert path is not None
        json.loads(path.read_text(encoding="utf-8"))  # must not raise

    def test_report_is_utf8(self, vault: Path) -> None:
        _run_script(vault)
        path = _find_repair_report(vault)
        assert path is not None
        path.read_bytes().decode("utf-8")  # must not raise

    @pytest.mark.parametrize("key", [
        "date", "generatedAt", "repairs", "failures", "warnings",
        "errorBuckets", "taskErrors",
    ])
    def test_required_keys_present(self, vault: Path, key: str) -> None:
        _run_script(vault)
        report = _load_repair_report(vault)
        assert key in report, f"Missing key in repair report: {key!r}"

    def test_date_field_is_today(self, vault: Path) -> None:
        _run_script(vault)
        report = _load_repair_report(vault)
        assert report["date"] == _today()

    def test_repairs_is_list(self, vault: Path) -> None:
        _run_script(vault)
        assert isinstance(_load_repair_report(vault)["repairs"], list)

    def test_failures_is_list(self, vault: Path) -> None:
        _run_script(vault)
        assert isinstance(_load_repair_report(vault)["failures"], list)

    def test_warnings_is_list(self, vault: Path) -> None:
        _run_script(vault)
        assert isinstance(_load_repair_report(vault)["warnings"], list)

    def test_error_buckets_is_dict(self, vault: Path) -> None:
        _run_script(vault)
        report = _load_repair_report(vault)
        buckets = report.get("errorBuckets") or {}
        assert isinstance(buckets, dict)

    def test_done_marker_includes_repair_count(self, vault: Path) -> None:
        _run_script(vault)
        log = _shared_log(vault).read_text(encoding="utf-8")
        assert "DONE" in log and "repairs=" in log

    def test_corrupt_tasks_json_failure_recorded(self, vault: Path) -> None:
        _tasks_conf(vault).write_text("{ invalid json }", encoding="utf-8")
        _run_script(vault)
        report = _load_repair_report(vault)
        assert len(report["failures"]) > 0

    def test_second_run_overwrites_report(self, vault: Path) -> None:
        _run_script(vault)
        report1 = _load_repair_report(vault)
        _run_script(vault)
        report2 = _load_repair_report(vault)
        # Both valid; one file per date
        reports = list(_reports_dir(vault).glob(f"repair-{_today()}*.json"))
        assert len(reports) == 1
        assert report2["date"] == _today()

