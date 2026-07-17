You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.system/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.system/config/<script_name>.json`)
     - Contains script-specific settings and overrides.
     - Always loaded after global config (can override global values).
     - Can be empty (`{}`) but must always exist.

2. **Output Format:**
   - You must output **two valid JSON objects** clearly labeled.
   - Use sensible, descriptive keys in `snake_case`.
   - Include meaningful `default` values for every setting.
   - Add a `"description"` field for each major setting when helpful.
   - Group related settings under logical sections if needed.

3. **What to Extract:**
   - Hardcoded paths (especially those derived from `__file__`)
   - Constants (BATCH_SIZE, thresholds, limits, etc.)
   - LLM settings (URL, model, provider, etc.)
   - File/directory references
   - Magic numbers and strings that are likely to change
   - Any environment-dependent behavior

4. **Rules:**
   - Prefer putting common things (project roots, LLM config, logging, shared directories) in **global**.
   - Put script-specific behavior (batch sizes, task-specific prompts, agent name, etc.) in **local**.
   - Make sure the JSONs contain good defaults so the script works even if the files are deleted.
   - Use clear, consistent naming.
   - Do not include code - only configuration.

---

**Script to analyze:**

# tests\test_cleanup_agent.py
"""Tests for cleanup.tools.cleanup_agent."""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Patch module-level paths before import so functions use tmp dirs
import importlib
import sys


@pytest.fixture
def agent_dirs(tmp_path):
    """Create a minimal .agents directory tree for cleanup tests."""
    agents = tmp_path / ".agents"
    # Per-agent log/report dirs
    for name in ("review", "repair", "cleanup"):
        (agents / name / "state" / "logs").mkdir(parents=True)
        (agents / name / "state" / "reports").mkdir(parents=True)
    # Runtime state
    (agents / "runtime" / "state" / "logs").mkdir(parents=True)
    (agents / "runtime" / "state").mkdir(parents=True, exist_ok=True)
    return agents


def _write_old_file(directory: Path, name: str, age_days: int) -> Path:
    """Write an empty file and backdate its mtime by age_days."""
    f = directory / name
    f.write_text("", encoding="utf-8")
    old_ts = time.time() - age_days * 86400
    import os
    os.utime(f, (old_ts, old_ts))
    return f


# ---------------------------------------------------------------------------
# _purge_dir
# ---------------------------------------------------------------------------

class TestPurgeDir:
    def test_deletes_files_older_than_cutoff(self, agent_dirs, tmp_path):
        from cleanup.tools.cleanup_agent import _purge_dir
        from shared.logger import Logger

        d = agent_dirs / "review" / "state" / "logs"
        old = _write_old_file(d, "old.log", age_days=100)
        new = _write_old_file(d, "new.log", age_days=10)

        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        deleted = _purge_dir(d, keep_days=90, log=log)

        assert deleted == 1
        assert not old.exists()
        assert new.exists()

    def test_returns_zero_for_missing_dir(self, agent_dirs, tmp_path):
        from cleanup.tools.cleanup_agent import _purge_dir
        from shared.logger import Logger

        missing = agent_dirs / "nonexistent" / "state" / "logs"
        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        assert _purge_dir(missing, keep_days=90, log=log) == 0

    def test_skips_directories(self, agent_dirs, tmp_path):
        from cleanup.tools.cleanup_agent import _purge_dir
        from shared.logger import Logger

        d = agent_dirs / "review" / "state" / "logs"
        subdir = d / "subdir"
        subdir.mkdir()
        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        # Should not raise; directories are skipped
        _purge_dir(d, keep_days=0, log=log)
        assert subdir.exists()


# ---------------------------------------------------------------------------
# purge_logs / purge_reports
# ---------------------------------------------------------------------------

class TestPurgeLogs:
    def test_scans_all_agent_log_dirs(self, agent_dirs, monkeypatch):
        from cleanup.tools import cleanup_agent
        from shared.logger import Logger

        monkeypatch.setattr(cleanup_agent, "_AGENTS_DIR", agent_dirs)

        d1 = agent_dirs / "review" / "state" / "logs"
        d2 = agent_dirs / "runtime" / "state" / "logs"
        old1 = _write_old_file(d1, "review_2024-01-01.log", 200)
        old2 = _write_old_file(d2, "automation_2024-01-01.log", 200)

        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        deleted = cleanup_agent.purge_logs(keep_days=90, log=log)

        assert deleted == 2
        assert not old1.exists()
        assert not old2.exists()


class TestPurgeReports:
    def test_scans_all_agent_report_dirs(self, agent_dirs, monkeypatch):
        from cleanup.tools import cleanup_agent
        from shared.logger import Logger

        monkeypatch.setattr(cleanup_agent, "_AGENTS_DIR", agent_dirs)

        d = agent_dirs / "repair" / "state" / "reports"
        old = _write_old_file(d, "repair-2024-01-01.json", 200)
        recent = _write_old_file(d, "repair-2026-06-10.json", 1)

        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        deleted = cleanup_agent.purge_reports(keep_days=90, log=log)

        assert deleted == 1
        assert not old.exists()
        assert recent.exists()


# ---------------------------------------------------------------------------
# trim_metrics
# ---------------------------------------------------------------------------

class TestTrimMetrics:
    def test_trims_to_max_runs(self, agent_dirs, tmp_path, monkeypatch):
        from cleanup.tools import cleanup_agent
        from shared.logger import Logger

        metrics_file = agent_dirs / "runtime" / "state" / "agent-metrics.json"
        monkeypatch.setattr(cleanup_agent, "_METRICS_FILE", metrics_file)

        runs = [{"startedAt": f"2024-01-{i:02d}T00:00:00Z"} for i in range(1, 21)]
        metrics_file.write_text(json.dumps({"vision-agent": {"runs": runs}}), encoding="utf-8")

        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        removed = cleanup_agent.trim_metrics(max_runs=10, log=log)

        assert removed == 10
        result = json.loads(metrics_file.read_text(encoding="utf-8"))
        assert len(result["vision-agent"]["runs"]) == 10
        # Most recent runs retained (last 10)
        assert result["vision-agent"]["runs"][0]["startedAt"] == "2024-01-11T00:00:00Z"

    def test_no_trim_when_under_limit(self, agent_dirs, monkeypatch):
        from cleanup.tools import cleanup_agent
        from shared.logger import Logger

        metrics_file = agent_dirs / "runtime" / "state" / "agent-metrics.json"
        monkeypatch.setattr(cleanup_agent, "_METRICS_FILE", metrics_file)

        runs = [{"startedAt": "2024-01-01T00:00:00Z"}] * 5
        original = json.dumps({"review-agent": {"runs": runs}})
        metrics_file.write_text(original, encoding="utf-8")

        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        removed = cleanup_agent.trim_metrics(max_runs=100, log=log)

        assert removed == 0
        # File content unchanged (no rewrite when nothing trimmed)
        assert json.loads(metrics_file.read_text(encoding="utf-8")) == json.loads(original)

    def test_returns_zero_when_file_missing(self, agent_dirs, monkeypatch):
        from cleanup.tools import cleanup_agent
        from shared.logger import Logger

        missing = agent_dirs / "runtime" / "state" / "agent-metrics.json"
        monkeypatch.setattr(cleanup_agent, "_METRICS_FILE", missing)

        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        assert cleanup_agent.trim_metrics(max_runs=100, log=log) == 0

    def test_strips_bom(self, agent_dirs, monkeypatch):
        from cleanup.tools import cleanup_agent
        from shared.logger import Logger

        metrics_file = agent_dirs / "runtime" / "state" / "agent-metrics.json"
        monkeypatch.setattr(cleanup_agent, "_METRICS_FILE", metrics_file)

        payload = {"a": {"runs": []}}
        # Write with BOM prefix (simulates Windows PS output)
        metrics_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))

        log = Logger("cleanup-agent", "cleanup_agent.py",
                     agent_dirs / "cleanup" / "state" / "logs",
                     agent_dirs / "runtime" / "state" / "logs" / "automation.log")
        removed = cleanup_agent.trim_metrics(max_runs=100, log=log)
        assert removed == 0  # no error raised, no trimming needed


# ---------------------------------------------------------------------------
# _write_report
# ---------------------------------------------------------------------------

class TestWriteReport:
    def test_writes_cleanup_report_json(self, agent_dirs, monkeypatch):
        from cleanup.tools import cleanup_agent

        reports_dir = agent_dirs / "cleanup" / "state" / "reports"
        monkeypatch.setattr(cleanup_agent, "_REPORTS_DIR", reports_dir)

        cleanup_agent._write_report(logs_deleted=3, reports_deleted=2, metrics_trimmed=10)

        today = datetime.now().strftime("%Y-%m-%d")
        out = reports_dir / f"cleanup-{today}.json"
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["logsDeleted"] == 3
        assert data["reportsDeleted"] == 2
        assert data["metricsTrimmed"] == 10
        assert data["date"] == today

    def test_write_is_atomic(self, agent_dirs, monkeypatch):
        from cleanup.tools import cleanup_agent

        reports_dir = agent_dirs / "cleanup" / "state" / "reports"
        monkeypatch.setattr(cleanup_agent, "_REPORTS_DIR", reports_dir)

        cleanup_agent._write_report(0, 0, 0)

        today = datetime.now().strftime("%Y-%m-%d")
        tmp = reports_dir / f"cleanup-{today}.tmp"
        assert not tmp.exists(), "tmp file should have been renamed to .json"


# ---------------------------------------------------------------------------
# _load_cleanup_days
# ---------------------------------------------------------------------------

class TestLoadCleanupDays:
    def test_reads_from_agent_json(self, tmp_path, monkeypatch):
        from cleanup.tools import cleanup_agent

        agent_json = tmp_path / "agent.json"
        agent_json.write_text(json.dumps({"cleanupDays": 30}), encoding="utf-8")
        monkeypatch.setattr(cleanup_agent, "_AGENT_JSON", agent_json)

        assert cleanup_agent._load_cleanup_days() == 30

    def test_defaults_to_90_when_field_missing(self, tmp_path, monkeypatch):
        from cleanup.tools import cleanup_agent

        agent_json = tmp_path / "agent.json"
        agent_json.write_text(json.dumps({"tasks": {}}), encoding="utf-8")
        monkeypatch.setattr(cleanup_agent, "_AGENT_JSON", agent_json)

        assert cleanup_agent._load_cleanup_days() == 90

    def test_defaults_to_90_when_file_missing(self, tmp_path, monkeypatch):
        from cleanup.tools import cleanup_agent

        monkeypatch.setattr(cleanup_agent, "_AGENT_JSON", tmp_path / "nonexistent.json")
        assert cleanup_agent._load_cleanup_days() == 90


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .system/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```

### Bonus: Loader Code Suggestion (for `shared/config.py`)

You can later create a simple loader like this:

```python
from pathlib import Path
import json

def load_config(script_path: Path):
    project_root = Path(__file__).resolve().parents[2]  # adjust as needed
    
    # Global
    global_path = project_root / "config" / "global.json"
    global_cfg = json.loads(global_path.read_text()) if global_path.exists() else {}
    
    # Local
    script_name = script_path.stem
    local_path = project_root / "config" / f"{script_name}.json"
    local_cfg = json.loads(local_path.read_text()) if local_path.exists() else {}
    
    # Merge (local overrides global)
    config = {**global_cfg, **local_cfg}
    return config
```

