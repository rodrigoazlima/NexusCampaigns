"""Tests for shared.loaders.load_vault_config."""

import json

import pytest
from pathlib import Path

from nexus.shared.loaders import load_llm_endpoint, load_vault_config, _find_project_root
from nexus.shared.config import LLMEndpointConfig, VaultConfig


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / ".knowledge-base").mkdir()
    return tmp_path


class TestFindProjectRoot:
    def test_finds_root_from_direct_parent(self, project_root):
        found = _find_project_root(project_root)
        assert found == project_root

    def test_finds_root_from_nested_subdirectory(self, project_root):
        nested = project_root / "a" / "b" / "c"
        nested.mkdir(parents=True)
        found = _find_project_root(nested)
        assert found == project_root

    def test_raises_if_no_knowledge_base(self, tmp_path):
        # _find_project_root walks to the drive root, so an ancestor of
        # tmp_path (e.g. %USERPROFILE%) holding .knowledge-base makes the
        # negative case untestable on this machine.
        if any((a / ".knowledge-base").is_dir() for a in [tmp_path, *tmp_path.parents]):
            pytest.skip("an ancestor of tmp_path contains .knowledge-base")
        with pytest.raises(FileNotFoundError, match=".knowledge-base"):
            _find_project_root(tmp_path)

    def test_finds_root_from_file_path(self, project_root):
        f = project_root / "agents" / "shared" / "loaders.py"
        f.parent.mkdir(parents=True)
        f.touch()
        found = _find_project_root(f)
        assert found == project_root


class TestLoadVaultConfig:
    def test_explicit_root_returns_config(self, project_root):
        cfg = load_vault_config(project_root)
        assert isinstance(cfg, VaultConfig)

    def test_vault_paths_point_to_knowledge_base(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.vault_root == project_root / ".knowledge-base"

    def test_inbox_path(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.inbox == project_root / ".knowledge-base" / "00-Inbox"

    def test_library_path(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.library == project_root / ".knowledge-base" / "02-Library"

    def test_system_paths_project_root(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.system_paths.project_root == project_root

    def test_llm_endpoints_present(self, project_root):
        cfg = load_vault_config(project_root)
        assert "vision" in cfg.llm_endpoints
        assert "lore" in cfg.llm_endpoints
        assert "classification" in cfg.llm_endpoints

    def test_vision_endpoint_port_1234(self, project_root):
        cfg = load_vault_config(project_root)
        assert "1234" in cfg.llm_endpoints["vision"].url

    def test_classification_endpoint_port_8080(self, project_root):
        cfg = load_vault_config(project_root)
        assert "8080" in cfg.llm_endpoints["classification"].url

    def test_vision_type_is_vision(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.llm_endpoints["vision"].type == "vision"

    def test_classification_type_is_text(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.llm_endpoints["classification"].type == "text"

    def test_auto_detect_from_real_project(self):
        # Auto-detect from this repo — .knowledge-base/ exists
        cfg = load_vault_config()
        assert cfg.vault_paths.vault_root.name == ".knowledge-base"
        assert cfg.vault_paths.vault_root.exists()

    def test_endpoints_are_frozen(self, project_root):
        cfg = load_vault_config(project_root)
        ep = cfg.llm_endpoints["vision"]
        with pytest.raises((AttributeError, TypeError)):
            ep.url = "http://other"  # type: ignore[misc]


_FALLBACK = LLMEndpointConfig(
    url      = "http://localhost:1234/v1/chat/completions",
    model    = "fallback-model",
    type     = "vision",
    provider = "lmstudio",
)

_REGISTRY_YAML = """\
version: 1
vault_root: "knowledge-base"
llm_endpoints:
  vision_llm:
    url: "http://localhost:1234/v1/chat/completions"
    model: "registry-model"
    type: vision
    provider: lm-studio
    timeout_seconds: 240
"""


class TestLoadLLMEndpoint:
    """timeout precedence: agent.json > registry.yaml > dataclass default (120)."""

    def test_default_timeout_without_registry(self, project_root):
        cfg = load_llm_endpoint("vision_llm", fallback=_FALLBACK, project_root=project_root)
        assert cfg == _FALLBACK
        assert cfg.timeout_seconds == 120

    def test_registry_timeout(self, project_root):
        (project_root / "agents").mkdir()
        (project_root / "agents" / "registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
        cfg = load_llm_endpoint("vision_llm", fallback=_FALLBACK, project_root=project_root)
        assert cfg.model == "registry-model"
        assert cfg.timeout_seconds == 240

    def test_agent_json_overrides_registry(self, project_root):
        agent_dir = project_root / "agents" / "vision"
        agent_dir.mkdir(parents=True)
        (project_root / "agents" / "registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
        (agent_dir / "agent.json").write_text(json.dumps({
            "tasks": {"vision-agent": {"llm": {"timeout_seconds": 300}}}
        }), encoding="utf-8")
        cfg = load_llm_endpoint(
            "vision_llm", fallback=_FALLBACK,
            agent_dir=agent_dir, task_id="vision-agent", project_root=project_root,
        )
        assert cfg.model == "registry-model"
        assert cfg.timeout_seconds == 300

    def test_agent_json_without_llm_block_keeps_registry_timeout(self, project_root):
        agent_dir = project_root / "agents" / "vision"
        agent_dir.mkdir(parents=True)
        (project_root / "agents" / "registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
        (agent_dir / "agent.json").write_text(json.dumps({
            "tasks": {"vision-agent": {"intervalSeconds": 900}}
        }), encoding="utf-8")
        cfg = load_llm_endpoint(
            "vision_llm", fallback=_FALLBACK,
            agent_dir=agent_dir, task_id="vision-agent", project_root=project_root,
        )
        assert cfg.timeout_seconds == 240

    def test_unknown_alias_falls_back(self, project_root):
        (project_root / "agents").mkdir()
        (project_root / "agents" / "registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
        cfg = load_llm_endpoint("nonexistent", fallback=_FALLBACK, project_root=project_root)
        assert cfg == _FALLBACK

    def test_model_key_overrides_registry_model(self, project_root):
        agent_dir = project_root / "agents" / "classification"
        agent_dir.mkdir(parents=True)
        (project_root / "agents" / "registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
        (agent_dir / "agent.json").write_text(json.dumps({
            "tasks": {"classification-agent": {"llm": {
                "text_model": "my-text-model",
                "vision_model": "my-vision-model",
            }}}
        }), encoding="utf-8")
        text_cfg = load_llm_endpoint(
            "vision_llm", fallback=_FALLBACK,
            agent_dir=agent_dir, task_id="classification-agent",
            project_root=project_root, model_key="text_model",
        )
        vision_cfg = load_llm_endpoint(
            "vision_llm", fallback=_FALLBACK,
            agent_dir=agent_dir, task_id="classification-agent",
            project_root=project_root, model_key="vision_model",
        )
        assert text_cfg.model == "my-text-model"
        assert vision_cfg.model == "my-vision-model"

    def test_model_key_absent_from_llm_block_keeps_registry_model(self, project_root):
        agent_dir = project_root / "agents" / "classification"
        agent_dir.mkdir(parents=True)
        (project_root / "agents" / "registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
        (agent_dir / "agent.json").write_text(json.dumps({
            "tasks": {"classification-agent": {"llm": {"timeout_seconds": 300}}}
        }), encoding="utf-8")
        cfg = load_llm_endpoint(
            "vision_llm", fallback=_FALLBACK,
            agent_dir=agent_dir, task_id="classification-agent",
            project_root=project_root, model_key="text_model",
        )
        assert cfg.model == "registry-model"
        assert cfg.timeout_seconds == 300

    def test_no_model_key_ignores_llm_block_models(self, project_root):
        agent_dir = project_root / "agents" / "classification"
        agent_dir.mkdir(parents=True)
        (project_root / "agents" / "registry.yaml").write_text(_REGISTRY_YAML, encoding="utf-8")
        (agent_dir / "agent.json").write_text(json.dumps({
            "tasks": {"classification-agent": {"llm": {"text_model": "my-text-model"}}}
        }), encoding="utf-8")
        cfg = load_llm_endpoint(
            "vision_llm", fallback=_FALLBACK,
            agent_dir=agent_dir, task_id="classification-agent",
            project_root=project_root,
        )
        assert cfg.model == "registry-model"
