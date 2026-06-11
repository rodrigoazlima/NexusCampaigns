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

# tests\test_interfaces.py
"""Tests for shared.interfaces — abstract contracts and exceptions."""

import pytest
from pathlib import Path
from abc import ABC
from unittest.mock import MagicMock

from shared.interfaces import (
    BaseAgent,
    IAgent,
    IFaceMatcher,
    IFrontmatterIO,
    IImageClassifier,
    ILLMClient,
    ILogger,
    INPCGenerator,
    IOrchestrator,
    IReportBuilder,
    IStateStore,
    ITagEnricher,
    ITokenRenderer,
    IVaultGuard,
    IWikiCompiler,
    LLMOfflineError,
    LLMResponseError,
    VaultWriteError,
)
from shared.config import VaultConfig, VaultPaths, SystemPaths


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_llm_offline_error_is_exception(self):
        exc = LLMOfflineError("server down")
        assert isinstance(exc, Exception)
        assert str(exc) == "server down"

    def test_llm_response_error_is_exception(self):
        exc = LLMResponseError("bad json")
        assert isinstance(exc, Exception)

    def test_vault_write_error_is_permission_error(self):
        exc = VaultWriteError("no write")
        assert isinstance(exc, PermissionError)

    def test_raise_and_catch_llm_offline(self):
        with pytest.raises(LLMOfflineError, match="offline"):
            raise LLMOfflineError("offline")

    def test_raise_and_catch_llm_response(self):
        with pytest.raises(LLMResponseError):
            raise LLMResponseError("bad response")

    def test_raise_and_catch_vault_write(self):
        with pytest.raises(VaultWriteError):
            raise VaultWriteError("protected dir")

    def test_vault_write_caught_as_permission_error(self):
        with pytest.raises(PermissionError):
            raise VaultWriteError("test")


# ---------------------------------------------------------------------------
# BaseAgent — ABC contract
# ---------------------------------------------------------------------------

class TestBaseAgent:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseAgent(cfg=None)  # type: ignore[arg-type]

    def test_concrete_subclass_works(self):
        class MyAgent(BaseAgent):
            TASK_ID = "my-agent"
            SCRIPT_BASENAME = "my_agent.py"

            def bootstrap(self): pass
            def run_batch(self): return (0, 0)
            def execute(self): return 0

        agent = MyAgent(cfg=None)  # type: ignore[arg-type]
        assert agent.execute() == 0
        assert agent.run_batch() == (0, 0)

    def test_batch_size_default(self):
        class MyAgent(BaseAgent):
            TASK_ID = "x"
            SCRIPT_BASENAME = "x.py"
            def bootstrap(self): pass
            def run_batch(self): return (0, 0)
            def execute(self): return 0

        assert MyAgent.BATCH_SIZE == 10

    def test_missing_run_batch_raises(self):
        class Incomplete(BaseAgent):
            TASK_ID = "x"
            SCRIPT_BASENAME = "x.py"
            def bootstrap(self): pass
            def execute(self): return 0

        with pytest.raises(TypeError):
            Incomplete(cfg=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# IAgent protocol — structural check
# ---------------------------------------------------------------------------

class TestIAgentProtocol:
    def test_concrete_class_satisfies_protocol(self):
        class GoodAgent:
            TASK_ID         = "good"
            SCRIPT_BASENAME = "good.py"
            BATCH_SIZE      = 5

            def execute(self) -> int: return 0
            def run_batch(self) -> tuple: return (0, 0)

        agent = GoodAgent()
        assert isinstance(agent, IAgent)

    def test_missing_execute_fails_protocol_check(self):
        class BadAgent:
            TASK_ID         = "bad"
            SCRIPT_BASENAME = "bad.py"
            BATCH_SIZE      = 5

            def run_batch(self): return (0, 0)
            # No execute()

        assert not isinstance(BadAgent(), IAgent)


# ---------------------------------------------------------------------------
# Abstract interface — must raise NotImplementedError
# ---------------------------------------------------------------------------

class TestAbstractInterfaces:
    def test_illm_client_abstract(self):
        with pytest.raises(TypeError):
            ILLMClient()  # type: ignore[abstract]

    def test_istate_store_abstract(self):
        with pytest.raises(TypeError):
            IStateStore()  # type: ignore[abstract]

    def test_ifrontmatter_io_abstract(self):
        with pytest.raises(TypeError):
            IFrontmatterIO()  # type: ignore[abstract]

    def test_ivault_guard_abstract(self):
        with pytest.raises(TypeError):
            IVaultGuard()  # type: ignore[abstract]

    def test_iimage_classifier_abstract(self):
        with pytest.raises(TypeError):
            IImageClassifier()  # type: ignore[abstract]

    def test_inpc_generator_abstract(self):
        with pytest.raises(TypeError):
            INPCGenerator()  # type: ignore[abstract]

    def test_itoken_renderer_abstract(self):
        with pytest.raises(TypeError):
            ITokenRenderer()  # type: ignore[abstract]

    def test_itag_enricher_abstract(self):
        with pytest.raises(TypeError):
            ITagEnricher()  # type: ignore[abstract]

    def test_iwiki_compiler_abstract(self):
        with pytest.raises(TypeError):
            IWikiCompiler()  # type: ignore[abstract]

    def test_ireport_builder_abstract(self):
        with pytest.raises(TypeError):
            IReportBuilder()  # type: ignore[abstract]

    def test_iorchestrator_abstract(self):
        with pytest.raises(TypeError):
            IOrchestrator()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# ILogger protocol
# ---------------------------------------------------------------------------

class TestILoggerProtocol:
    def test_concrete_satisfies_logger_protocol(self):
        class GoodLogger:
            def info(self, msg: str) -> None: pass
            def warning(self, msg: str) -> None: pass
            def error(self, msg: str) -> None: pass
            def start(self) -> float: return 0.0
            def done(self, t0, *, key, count, failed) -> None: pass

        assert isinstance(GoodLogger(), ILogger)

    def test_missing_method_fails_protocol(self):
        class PartialLogger:
            def info(self, msg): pass
            # missing warning, error, start, done

        assert not isinstance(PartialLogger(), ILogger)


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

