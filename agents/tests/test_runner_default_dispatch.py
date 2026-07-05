"""runner._load_agent_dispatch falls back to registry.yaml's default_dispatch
when an agent has no agent.json (or no entry for the requested task_id)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared.models import AgentRegistryEntry, DefaultDispatchConfig, RegistryConfig

_RUNNER_PATH = (
    Path(__file__).resolve().parents[1] / "runtime" / "tools" / "runner.py"
)


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("runner_under_test", _RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runner_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner(tmp_path):
    mod = _load_runner_module()
    mod._AGENTS_DIR = tmp_path / "agents"
    mod._PROJECT_ROOT = tmp_path
    (mod._AGENTS_DIR / "someagent").mkdir(parents=True)
    return mod


def _fake_registry(tools=("tools/someagent_agent.py",)):
    return RegistryConfig(
        vault_root=".knowledge-base",
        agents={
            "someagent": AgentRegistryEntry(
                status="active",
                task_id="someagent-agent",
                tools=list(tools),
            ),
        },
        default_dispatch=DefaultDispatchConfig(
            type="lm-studio",
            base_url="http://localhost:1234/v1",
            model="qwen/qwen3.5-9b",
            timeout_seconds=1800,
            system_file="prompts/system.md",
        ),
    )


def test_falls_back_to_default_dispatch_when_agent_json_missing(runner, monkeypatch):
    monkeypatch.setattr(runner, "load_registry", lambda project_root: _fake_registry())
    log = MagicMock()

    dispatch = runner._load_agent_dispatch("someagent-agent", log)

    assert dispatch is not None
    assert dispatch.type == "lm-studio"
    assert dispatch.lm_studio.model == "qwen/qwen3.5-9b"
    assert dispatch.lm_studio.tools_module == "someagent.tools.someagent_agent"


def test_returns_none_when_registry_has_no_tools_for_agent(runner, monkeypatch):
    monkeypatch.setattr(runner, "load_registry", lambda project_root: _fake_registry(tools=()))
    log = MagicMock()

    dispatch = runner._load_agent_dispatch("someagent-agent", log)

    assert dispatch is None


def test_returns_none_when_registry_has_no_default_dispatch(runner, monkeypatch):
    registry = _fake_registry()
    registry.default_dispatch = None
    monkeypatch.setattr(runner, "load_registry", lambda project_root: registry)
    log = MagicMock()

    dispatch = runner._load_agent_dispatch("someagent-agent", log)

    assert dispatch is None
