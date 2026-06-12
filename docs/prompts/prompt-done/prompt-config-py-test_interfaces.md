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

from shared.config import VaultConfig, VaultPaths, SystemPaths
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

        agent = MyAgent(cfg=None)  # type: ignore[arg-type]
        assert agent.run_batch() == (0, 0)

    def test_subclass_can_override_execute(self):
        class MyAgent(BaseAgent):
            TASK_ID = "my-agent"
            SCRIPT_BASENAME = "my_agent.py"

            def bootstrap(self): pass
            def run_batch(self): return (0, 0)
            def execute(self): return 42

        agent = MyAgent(cfg=None)  # type: ignore[arg-type]
        assert agent.execute() == 42

    def test_batch_size_default(self):
        class MyAgent(BaseAgent):
            TASK_ID = "x"
            SCRIPT_BASENAME = "x.py"
            def bootstrap(self): pass
            def run_batch(self): return (0, 0)

        assert MyAgent.BATCH_SIZE == 10

    def test_done_key_default(self):
        class MyAgent(BaseAgent):
            TASK_ID = "x"
            SCRIPT_BASENAME = "x.py"
            def bootstrap(self): pass
            def run_batch(self): return (0, 0)

        assert MyAgent.DONE_KEY == "processed"

    def test_missing_run_batch_raises(self):
        class Incomplete(BaseAgent):
            TASK_ID = "x"
            SCRIPT_BASENAME = "x.py"
            def bootstrap(self): pass

        with pytest.raises(TypeError):
            Incomplete(cfg=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BaseAgent — default execute() lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture
def vault_cfg(tmp_path):
    kb = tmp_path / "knowledge-base"
    kb.mkdir()
    return VaultConfig(
        vault_paths  = VaultPaths(vault_root=kb),
        system_paths = SystemPaths(project_root=tmp_path),
    )


class TestBaseAgentDefaultExecute:
    def _make_agent(self, cfg, *, batch_result=(3, 0), done_key="processed", raises=None):
        class ConcreteAgent(BaseAgent):
            TASK_ID         = "test-agent"
            SCRIPT_BASENAME = "test_agent.py"
            DONE_KEY        = done_key
            bootstrapped    = False

            def bootstrap(self):
                ConcreteAgent.bootstrapped = True

            def run_batch(self):
                if raises:
                    raise raises
                return batch_result

        return ConcreteAgent(cfg=cfg)

    def test_returns_0_on_success(self, vault_cfg):
        agent = self._make_agent(vault_cfg, batch_result=(5, 0))
        assert agent.execute() == 0

    def test_returns_1_when_failures(self, vault_cfg):
        agent = self._make_agent(vault_cfg, batch_result=(5, 2))
        assert agent.execute() == 1

    def test_calls_bootstrap_before_run_batch(self, vault_cfg):
        agent = self._make_agent(vault_cfg)
        agent.execute()
        assert agent.__class__.bootstrapped is True

    def test_emits_start_and_done_to_master_log(self, vault_cfg, tmp_path):
        agent = self._make_agent(vault_cfg, batch_result=(4, 0))
        agent.execute()
        master = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
        content = master.read_text(encoding="utf-8")
        assert "--- START ---" in content
        assert "--- DONE (" in content

    def test_done_line_contains_count(self, vault_cfg, tmp_path):
        agent = self._make_agent(vault_cfg, batch_result=(7, 0))
        agent.execute()
        master = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
        assert "processed: 7" in master.read_text(encoding="utf-8")

    def test_done_line_uses_done_key(self, vault_cfg, tmp_path):
        agent = self._make_agent(vault_cfg, batch_result=(2, 0), done_key="classified")
        agent.execute()
        master = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
        assert "classified: 2" in master.read_text(encoding="utf-8")

    def test_exception_in_run_batch_returns_1(self, vault_cfg):
        agent = self._make_agent(vault_cfg, raises=RuntimeError("boom"))
        assert agent.execute() == 1

    def test_exception_logged_to_master(self, vault_cfg, tmp_path):
        agent = self._make_agent(vault_cfg, raises=RuntimeError("test-error"))
        agent.execute()
        master = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
        assert "test-error" in master.read_text(encoding="utf-8")

    def test_per_agent_daily_log_created(self, vault_cfg, tmp_path):
        agent = self._make_agent(vault_cfg)
        agent.execute()
        # agent_name = "test-agent".removesuffix("-agent") = "test"
        logs_dir = tmp_path / ".agents" / "test" / "state" / "logs"
        daily_files = list(logs_dir.glob("test_agent_*.log"))
        assert len(daily_files) == 1

    def test_logger_stored_on_instance(self, vault_cfg):
        agent = self._make_agent(vault_cfg)
        agent.execute()
        assert hasattr(agent, "_logger")


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

