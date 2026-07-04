"""Tests for shared.loaders.load_vault_config."""

import pytest
from pathlib import Path

from shared.loaders import load_vault_config, _find_project_root
from shared.config import VaultConfig


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / "knowledge-base").mkdir()
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
        with pytest.raises(FileNotFoundError, match="knowledge-base"):
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
        assert cfg.vault_paths.vault_root == project_root / "knowledge-base"

    def test_inbox_path(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.inbox == project_root / "knowledge-base" / "00-Inbox"

    def test_library_path(self, project_root):
        cfg = load_vault_config(project_root)
        assert cfg.vault_paths.library == project_root / "knowledge-base" / "02-Library"

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
        # Auto-detect from this repo — knowledge-base/ exists
        cfg = load_vault_config()
        assert cfg.vault_paths.vault_root.name == "knowledge-base"
        assert cfg.vault_paths.vault_root.exists()

    def test_endpoints_are_frozen(self, project_root):
        cfg = load_vault_config(project_root)
        ep = cfg.llm_endpoints["vision"]
        with pytest.raises((AttributeError, TypeError)):
            ep.url = "http://other"  # type: ignore[misc]
