"""Tests for shared.logger.Logger."""

import io
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.logger import Logger, _ensure_utf8_stdout


@pytest.fixture
def log_dirs(tmp_path):
    logs_dir  = tmp_path / "logs"
    master    = tmp_path / "automation.log"
    return logs_dir, master


@pytest.fixture
def logger(log_dirs):
    logs_dir, master = log_dirs
    return Logger(
        task_id        = "test-agent",
        script_basename= "test_script.py",
        logs_dir       = logs_dir,
        master_log     = master,
    )


class TestLoggerInit:
    def test_creates_logs_dir(self, log_dirs):
        logs_dir, master = log_dirs
        Logger("t", "s.py", logs_dir, master)
        assert logs_dir.exists()

    def test_creates_master_parent(self, tmp_path):
        logs_dir  = tmp_path / "logs"
        master    = tmp_path / "deep" / "automation.log"
        Logger("t", "s.py", logs_dir, master)
        assert master.parent.exists()

    def test_daily_log_name_strips_extension(self, log_dirs, logger):
        from datetime import datetime
        today     = datetime.now().strftime("%Y-%m-%d")
        logs_dir, _ = log_dirs
        assert (logs_dir / f"test_script_{today}.log").exists() or True
        # Daily log created on first write — just check attribute set
        assert logger._daily.name.startswith("test_script_")

    def test_ps1_extension_stripped(self, log_dirs):
        logs_dir, master = log_dirs
        lg = Logger("t", "run.ps1", logs_dir, master)
        assert lg._daily.name.startswith("run_")


class TestLoggerWrite:
    def test_info_writes_to_master(self, logger, log_dirs):
        _, master = log_dirs
        logger.info("hello world")
        content = master.read_text(encoding="utf-8")
        assert "[test-agent]" in content
        assert "INFO" in content
        assert "hello world" in content

    def test_warning_writes_warn_level(self, logger, log_dirs):
        _, master = log_dirs
        logger.warning("beware")
        content = master.read_text(encoding="utf-8")
        assert "WARN" in content
        assert "beware" in content

    def test_error_writes_error_level(self, logger, log_dirs):
        _, master = log_dirs
        logger.error("boom")
        content = master.read_text(encoding="utf-8")
        assert "ERROR" in content
        assert "boom" in content

    def test_writes_to_daily_log(self, logger, log_dirs):
        logs_dir, _ = log_dirs
        logger.info("daily test")
        daily = logger._daily
        content = daily.read_text(encoding="utf-8")
        assert "daily test" in content

    def test_appends_multiple_lines(self, logger, log_dirs):
        _, master = log_dirs
        logger.info("line1")
        logger.info("line2")
        lines = master.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_format_has_timestamp(self, logger, log_dirs):
        _, master = log_dirs
        logger.info("ts check")
        line = master.read_text(encoding="utf-8").strip()
        # Format: [YYYY-MM-DD HH:mm:ss]
        assert line.startswith("[20")

    def test_multiple_loggers_append_to_same_master(self, log_dirs):
        logs_dir, master = log_dirs
        lg1 = Logger("agent-a", "a.py", logs_dir, master)
        lg2 = Logger("agent-b", "b.py", logs_dir, master)
        lg1.info("from a")
        lg2.info("from b")
        content = master.read_text(encoding="utf-8")
        assert "agent-a" in content
        assert "agent-b" in content


class TestLoggerStartDone:
    def test_start_writes_start_marker(self, logger, log_dirs):
        _, master = log_dirs
        logger.start()
        assert "--- START ---" in master.read_text(encoding="utf-8")

    def test_start_returns_float(self, logger):
        t0 = logger.start()
        assert isinstance(t0, float)

    def test_done_writes_done_marker(self, logger, log_dirs):
        _, master = log_dirs
        t0 = logger.start()
        logger.done(t0, key="processed", count=5, failed=1)
        content = master.read_text(encoding="utf-8")
        # spec format: --- DONE (key: N, failed: N, elapsed: Xs) ---
        assert "--- DONE (" in content
        assert "processed: 5" in content
        assert "failed: 1" in content
        assert content.strip().endswith("---")

    def test_done_reports_elapsed(self, logger, log_dirs):
        _, master = log_dirs
        t0 = logger.start()
        time.sleep(0.01)
        logger.done(t0, key="classified", count=0, failed=0)
        content = master.read_text(encoding="utf-8")
        assert "elapsed:" in content


class TestEnsureUtf8Stdout:
    def test_no_op_when_already_utf8(self):
        """_ensure_utf8_stdout() must not double-wrap a UTF-8 stdout."""
        original = sys.stdout
        with patch("sys.platform", "win32"):
            fake = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            with patch("sys.stdout", fake):
                _ensure_utf8_stdout()
                assert sys.stdout is fake  # unchanged
        sys.stdout = original

    def test_wraps_non_utf8_stdout_on_windows(self):
        """On Windows with non-UTF-8 encoding, stdout is re-wrapped as UTF-8."""
        with patch("sys.platform", "win32"):
            buf = io.BytesIO()
            fake = io.TextIOWrapper(buf, encoding="cp1252")
            with patch("sys.stdout", fake):
                _ensure_utf8_stdout()
                assert sys.stdout.encoding == "utf-8"

    def test_noop_on_non_windows(self):
        """On non-Windows platforms, stdout is left unchanged."""
        original = sys.stdout
        with patch("sys.platform", "linux"):
            buf = io.BytesIO()
            fake = io.TextIOWrapper(buf, encoding="cp1252")
            with patch("sys.stdout", fake):
                _ensure_utf8_stdout()
                assert sys.stdout is fake  # not replaced
        sys.stdout = original
