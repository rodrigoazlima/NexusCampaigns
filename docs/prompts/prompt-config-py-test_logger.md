You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.shared/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.shared/config/<script_name>.json`)
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
   - Do not include code — only configuration.

---

**Script to analyze:**

# tests\test_logger.py
"""Tests for shared.logger.Logger."""

import time
from pathlib import Path

import pytest

from shared.logger import Logger


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
        assert "--- DONE ---" in content
        assert "processed: 5" in content
        assert "failed=1" in content

    def test_done_reports_elapsed(self, logger, log_dirs):
        _, master = log_dirs
        t0 = logger.start()
        time.sleep(0.01)
        logger.done(t0, key="classified", count=0, failed=0)
        content = master.read_text(encoding="utf-8")
        assert "elapsed=" in content


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .shared/config/
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

