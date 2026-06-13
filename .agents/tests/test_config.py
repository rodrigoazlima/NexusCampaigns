"""Tests for shared.config — dataclasses."""

from pathlib import Path
import pytest
from shared.config import LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths


class TestLLMEndpointConfig:
    def test_fields(self):
        cfg = LLMEndpointConfig(
            url="http://localhost:1234/v1/chat/completions",
            model="qwen3-vl",
            type="vision",
            provider="lmstudio",
        )
        assert cfg.url.startswith("http")
        assert cfg.type == "vision"

    def test_frozen(self):
        cfg = LLMEndpointConfig(url="http://x", model="m", type="text", provider="p")
        with pytest.raises((AttributeError, TypeError)):
            cfg.url = "other"  # type: ignore[misc]


class TestVaultPaths:
    def test_derived_paths(self, tmp_path):
        vp = VaultPaths(vault_root=tmp_path / "knowledge-base")
        assert vp.inbox   == tmp_path / "knowledge-base" / "00-Inbox"
        assert vp.library == tmp_path / "knowledge-base" / "02-Library"
        assert vp.processing == tmp_path / "knowledge-base" / "01-Processing"
        assert vp.campaigns  == tmp_path / "knowledge-base" / "03-Campaigns"
        assert vp.relationships == tmp_path / "knowledge-base" / "04-Relationships"
        assert vp.assets   == tmp_path / "knowledge-base" / "05-Assets"
        assert vp.archive  == tmp_path / "knowledge-base" / "99-Archive"

    def test_frozen(self, tmp_path):
        vp = VaultPaths(vault_root=tmp_path)
        with pytest.raises((AttributeError, TypeError)):
            vp.vault_root = tmp_path / "other"  # type: ignore[misc]


class TestSystemPaths:
    def test_derived_paths(self, tmp_path):
        sp = SystemPaths(project_root=tmp_path)
        assert sp.agents_dir   == tmp_path / ".agents"
        assert sp.system_state == tmp_path / ".system" / "state"
        assert sp.logs_dir     == tmp_path / ".agents" / "runtime" / "state" / "logs"
        assert sp.reports_dir  == tmp_path / ".agents" / "review" / "state" / "reports"

    def test_agent_state(self, tmp_path):
        sp = SystemPaths(project_root=tmp_path)
        assert sp.agent_state("vision") == tmp_path / ".agents" / "vision" / "state"

    def test_frozen(self, tmp_path):
        sp = SystemPaths(project_root=tmp_path)
        with pytest.raises((AttributeError, TypeError)):
            sp.project_root = tmp_path  # type: ignore[misc]


class TestVaultConfig:
    def test_compose(self, tmp_path):
        vp  = VaultPaths(vault_root=tmp_path / "knowledge-base")
        sp  = SystemPaths(project_root=tmp_path)
        cfg = VaultConfig(vault_paths=vp, system_paths=sp)
        assert cfg.llm_endpoints == {}

    def test_with_endpoints(self, tmp_path):
        ep = LLMEndpointConfig(url="http://x", model="m", type="text", provider="p")
        vp = VaultPaths(vault_root=tmp_path)
        sp = SystemPaths(project_root=tmp_path)
        cfg = VaultConfig(vault_paths=vp, system_paths=sp, llm_endpoints={"k": ep})
        assert "k" in cfg.llm_endpoints
