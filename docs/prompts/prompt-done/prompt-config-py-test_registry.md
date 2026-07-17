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

# tests\test_registry.py
"""Tests for agent-registry.spec.md - RegistryConfig models and load_registry()."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from shared.loaders import load_registry, load_vault_config
from shared.models import (
    AgentRegistryEntry,
    AgentSharedStateSpec,
    LLMEndpointSpec,
    RegistryConfig,
    SharedStateFileSpec,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_REGISTRY = textwrap.dedent("""\
    version: 1
    vault_root: "/tmp/vault/knowledge-base"
    agents_dir: ".agents"
    shared_dir: ".system"

    llm_endpoints:
      vision_llm:
        url: "http://localhost:1234/v1/chat/completions"
        model: "qwen3-vl-4b-instruct"
        type: vision
        provider: lm-studio
      local_router:
        url: "http://localhost:8080/v1/chat/completions"
        model: "auto"
        type: text
        provider: local-router

    execution_order:
      - runtime
      - repair
      - ingestion
      - vision

    shared_state_files:
      inbox-queue.json:
        path: .system/state/inbox-queue.json
        owner: ingestion
        updaters:
          - vision
          - lore

    agents:
      runtime:
        status: active
        description: "Dispatcher"
        interval_seconds: 60
        llm: none

      ingestion:
        status: active
        task_id: ingestion-agent
        interval_seconds: 3600
        llm: none
        tools:
          - tools/ingestion_agent.py
        shared_state:
          writes:
            - .system/state/inbox-queue.json

      vision:
        status: active
        task_id: vision-agent
        interval_seconds: 3600
        llm: vision_llm
        tools:
          - tools/classify_images.py
        shared_state:
          reads:
            - .system/state/inbox-queue.json
          updates:
            - .system/state/inbox-queue.json

      curator:
        status: planned
        dependencies:
          - review
          - classification
        llm: TBD
""")


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / "knowledge-base").mkdir()
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    (agents_dir / "registry.yaml").write_text(_MINIMAL_REGISTRY, encoding="utf-8")
    return tmp_path


@pytest.fixture
def registry(project_root: Path) -> RegistryConfig:
    return load_registry(project_root)


# ---------------------------------------------------------------------------
# load_registry - basic parsing
# ---------------------------------------------------------------------------

class TestLoadRegistry:
    def test_returns_registry_config(self, registry: RegistryConfig) -> None:
        assert isinstance(registry, RegistryConfig)

    def test_version(self, registry: RegistryConfig) -> None:
        assert registry.version == 1

    def test_agents_dir(self, registry: RegistryConfig) -> None:
        assert registry.agents_dir == ".agents"

    def test_shared_dir(self, registry: RegistryConfig) -> None:
        assert registry.system_dir == ".system"

    def test_raises_when_no_registry(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge-base").mkdir()
        with pytest.raises(FileNotFoundError, match="registry.yaml"):
            load_registry(tmp_path)

    def test_auto_detect(self) -> None:
        # Uses the live project registry.yaml
        reg = load_registry()
        assert isinstance(reg, RegistryConfig)
        assert reg.version == 1


# ---------------------------------------------------------------------------
# LLM endpoints
# ---------------------------------------------------------------------------

class TestLLMEndpoints:
    def test_vision_llm_present(self, registry: RegistryConfig) -> None:
        assert "vision_llm" in registry.llm_endpoints

    def test_local_router_present(self, registry: RegistryConfig) -> None:
        assert "local_router" in registry.llm_endpoints

    def test_vision_llm_url(self, registry: RegistryConfig) -> None:
        assert "1234" in registry.llm_endpoints["vision_llm"].url

    def test_local_router_url(self, registry: RegistryConfig) -> None:
        assert "8080" in registry.llm_endpoints["local_router"].url

    def test_vision_llm_type(self, registry: RegistryConfig) -> None:
        assert registry.llm_endpoints["vision_llm"].type == "vision"

    def test_local_router_type(self, registry: RegistryConfig) -> None:
        assert registry.llm_endpoints["local_router"].type == "text"

    def test_get_endpoint_found(self, registry: RegistryConfig) -> None:
        ep = registry.get_endpoint("vision_llm")
        assert ep is not None
        assert ep.model == "qwen3-vl-4b-instruct"

    def test_get_endpoint_missing(self, registry: RegistryConfig) -> None:
        assert registry.get_endpoint("nonexistent") is None

    def test_endpoint_is_llm_endpoint_spec(self, registry: RegistryConfig) -> None:
        ep = registry.llm_endpoints["vision_llm"]
        assert isinstance(ep, LLMEndpointSpec)


# ---------------------------------------------------------------------------
# Execution order
# ---------------------------------------------------------------------------

class TestExecutionOrder:
    def test_execution_order_is_list(self, registry: RegistryConfig) -> None:
        assert isinstance(registry.execution_order, list)

    def test_runtime_is_first(self, registry: RegistryConfig) -> None:
        assert registry.execution_order[0] == "runtime"

    def test_all_entries_are_strings(self, registry: RegistryConfig) -> None:
        assert all(isinstance(e, str) for e in registry.execution_order)

    def test_live_registry_execution_order(self) -> None:
        reg = load_registry()
        assert "runtime" in reg.execution_order
        assert "cleanup" in reg.execution_order


# ---------------------------------------------------------------------------
# Shared state files
# ---------------------------------------------------------------------------

class TestSharedStateFiles:
    def test_inbox_queue_present(self, registry: RegistryConfig) -> None:
        assert "inbox-queue.json" in registry.system_state_files

    def test_inbox_queue_owner(self, registry: RegistryConfig) -> None:
        spec = registry.system_state_files["inbox-queue.json"]
        assert spec.owner == "ingestion"

    def test_inbox_queue_updaters(self, registry: RegistryConfig) -> None:
        spec = registry.system_state_files["inbox-queue.json"]
        assert "vision" in spec.updaters

    def test_spec_is_shared_state_file_spec(self, registry: RegistryConfig) -> None:
        spec = registry.system_state_files["inbox-queue.json"]
        assert isinstance(spec, SharedStateFileSpec)


# ---------------------------------------------------------------------------
# Agent entries
# ---------------------------------------------------------------------------

class TestAgentEntries:
    def test_agents_dict_present(self, registry: RegistryConfig) -> None:
        assert len(registry.agents) > 0

    def test_runtime_agent_active(self, registry: RegistryConfig) -> None:
        assert registry.agents["runtime"].status == "active"

    def test_curator_agent_planned(self, registry: RegistryConfig) -> None:
        assert registry.agents["curator"].status == "planned"

    def test_ingestion_has_task_id(self, registry: RegistryConfig) -> None:
        assert registry.agents["ingestion"].task_id == "ingestion-agent"

    def test_ingestion_interval(self, registry: RegistryConfig) -> None:
        assert registry.agents["ingestion"].interval_seconds == 3600

    def test_vision_llm_alias(self, registry: RegistryConfig) -> None:
        assert registry.agents["vision"].llm == "vision_llm"

    def test_ingestion_tools(self, registry: RegistryConfig) -> None:
        assert "tools/ingestion_agent.py" in registry.agents["ingestion"].tools

    def test_agent_is_agent_registry_entry(self, registry: RegistryConfig) -> None:
        assert isinstance(registry.agents["vision"], AgentRegistryEntry)

    def test_curator_dependencies(self, registry: RegistryConfig) -> None:
        deps = registry.agents["curator"].dependencies
        assert "review" in deps and "classification" in deps


# ---------------------------------------------------------------------------
# Shared state spec on agents
# ---------------------------------------------------------------------------

class TestAgentSharedState:
    def test_vision_reads_inbox_queue(self, registry: RegistryConfig) -> None:
        ss = registry.agents["vision"].system_state
        assert ss is not None
        assert any("inbox-queue.json" in p for p in ss.reads)

    def test_vision_updates_inbox_queue(self, registry: RegistryConfig) -> None:
        ss = registry.agents["vision"].system_state
        assert ss is not None
        assert any("inbox-queue.json" in p for p in ss.updates)

    def test_ingestion_writes_inbox_queue(self, registry: RegistryConfig) -> None:
        ss = registry.agents["ingestion"].system_state
        assert ss is not None
        assert any("inbox-queue.json" in p for p in ss.writes)

    def test_shared_state_is_spec(self, registry: RegistryConfig) -> None:
        ss = registry.agents["ingestion"].system_state
        assert isinstance(ss, AgentSharedStateSpec)


# ---------------------------------------------------------------------------
# active_agents / planned_agents helpers
# ---------------------------------------------------------------------------

class TestRegistryHelpers:
    def test_active_agents_excludes_planned(self, registry: RegistryConfig) -> None:
        active = registry.active_agents()
        assert "curator" not in active

    def test_active_agents_includes_runtime(self, registry: RegistryConfig) -> None:
        assert "runtime" in registry.active_agents()

    def test_planned_agents_excludes_active(self, registry: RegistryConfig) -> None:
        planned = registry.planned_agents()
        assert "runtime" not in planned

    def test_planned_agents_includes_curator(self, registry: RegistryConfig) -> None:
        assert "curator" in registry.planned_agents()

    def test_live_registry_has_planned_agents(self) -> None:
        reg = load_registry()
        planned = reg.planned_agents()
        assert len(planned) > 0
        # Spec lists: canon, relationship, deduplication, curator, search,
        # adventure-builder, session-builder, encounter-builder
        assert "curator" in planned or "canon" in planned


# ---------------------------------------------------------------------------
# load_vault_config - registry integration
# ---------------------------------------------------------------------------

class TestLoadVaultConfigWithRegistry:
    def test_uses_registry_endpoints(self, project_root: Path) -> None:
        cfg = load_vault_config(project_root)
        # registry.yaml uses vision_llm / local_router - not legacy aliases
        assert "vision_llm" in cfg.llm_endpoints
        assert "local_router" in cfg.llm_endpoints

    def test_registry_endpoint_url(self, project_root: Path) -> None:
        cfg = load_vault_config(project_root)
        assert "1234" in cfg.llm_endpoints["vision_llm"].url

    def test_falls_back_to_defaults_without_registry(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge-base").mkdir()
        cfg = load_vault_config(tmp_path)
        # Fallback uses legacy aliases
        assert "vision" in cfg.llm_endpoints
        assert "lore" in cfg.llm_endpoints
        assert "classification" in cfg.llm_endpoints


# ---------------------------------------------------------------------------
# Live registry consistency checks
# ---------------------------------------------------------------------------

class TestLiveRegistryConsistency:
    """Validate the actual registry.yaml against spec invariants."""

    @pytest.fixture(autouse=True)
    def _reg(self) -> None:
        self.reg = load_registry()

    def test_all_active_agents_have_interval(self) -> None:
        for name, agent in self.reg.active_agents().items():
            if name == "runtime":
                continue
            assert agent.interval_seconds is not None, \
                f"Active agent '{name}' missing interval_seconds"

    def test_all_active_agents_have_task_id_except_runtime(self) -> None:
        for name, agent in self.reg.active_agents().items():
            if name == "runtime":
                continue
            assert agent.task_id is not None, \
                f"Active agent '{name}' missing task_id"

    def test_execution_order_agents_exist(self) -> None:
        for name in self.reg.execution_order:
            assert name in self.reg.agents, \
                f"execution_order entry '{name}' not in agents dict"

    def test_llm_aliases_resolve(self) -> None:
        for name, agent in self.reg.active_agents().items():
            llm = agent.llm
            if llm and llm not in ("none", "TBD", None):
                assert llm in self.reg.llm_endpoints, \
                    f"Agent '{name}' references unknown llm alias '{llm}'"

    def test_shared_state_owners_exist(self) -> None:
        for fname, spec in self.reg.system_state_files.items():
            assert spec.owner in self.reg.agents, \
                f"shared_state_files '{fname}' owner '{spec.owner}' not in agents"

    def test_planned_agents_have_dependencies_list(self) -> None:
        for name, agent in self.reg.planned_agents().items():
            assert isinstance(agent.dependencies, list), \
                f"Planned agent '{name}' dependencies is not a list"


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

