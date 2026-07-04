"""Config loader — builds VaultConfig and RegistryConfig from project root.

config.py declares the VaultConfig structure; this module resolves it from disk.
registry.yaml (agent-registry.spec.md) is the single source of truth for
LLM endpoints, agent definitions, and execution order.

Auto-discovery: walks up from __file__ until finding a directory that
contains knowledge-base/. Explicit root overrides auto-detect.

Fallback endpoints (no registry.yaml present) match llm-integration.spec.md:
  vision/lore  → localhost:1234  (Qwen3-VL)
  classification → localhost:8080 (unspecified model)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from .config import LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths
from .models import RegistryConfig

_REGISTRY_RELATIVE = "agents/registry.yaml"

_DEFAULT_ENDPOINTS: dict[str, LLMEndpointConfig] = {
    "vision": LLMEndpointConfig(
        url      = "http://localhost:1234/v1/chat/completions",
        model    = "qwen3-vl-4b-instruct",
        type     = "vision",
        provider = "lmstudio",
    ),
    "lore": LLMEndpointConfig(
        url      = "http://localhost:1234/v1/chat/completions",
        model    = "qwen3-vl-4b-instruct",
        type     = "vision",
        provider = "lmstudio",
    ),
    "classification": LLMEndpointConfig(
        url      = "http://localhost:8080/v1/chat/completions",
        model    = "unspecified",
        type     = "text",
        provider = "lmstudio",
    ),
}


def _find_project_root(start: Path) -> Path:
    """Walk up from start until a directory containing knowledge-base/ is found."""
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "knowledge-base").is_dir():
            return candidate
    raise FileNotFoundError(
        f"No project root found (missing knowledge-base/) searching up from {start}"
    )


def load_registry(project_root: Optional[Path] = None) -> RegistryConfig:
    """Parse agents/registry.yaml and return a validated RegistryConfig.

    Args:
        project_root: Explicit project root. Auto-detects if None.

    Raises:
        FileNotFoundError: If registry.yaml does not exist.
        pydantic.ValidationError: If the YAML fails schema validation.
    """
    if project_root is None:
        project_root = _find_project_root(Path(__file__).resolve().parent)

    registry_path = project_root / _REGISTRY_RELATIVE
    if not registry_path.exists():
        raise FileNotFoundError(f"registry.yaml not found: {registry_path}")

    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    return RegistryConfig.model_validate(raw)


def load_vault_config(project_root: Optional[Path] = None) -> VaultConfig:
    """Build a VaultConfig for the current project.

    Reads llm_endpoints from agents/registry.yaml when present.
    Falls back to hardcoded defaults when registry.yaml is absent.

    Args:
        project_root: Explicit project root. Auto-detects if None.
    """
    if project_root is None:
        project_root = _find_project_root(Path(__file__).resolve().parent)

    registry_path = project_root / _REGISTRY_RELATIVE
    if registry_path.exists():
        try:
            registry = load_registry(project_root)
            endpoints: dict[str, LLMEndpointConfig] = {
                alias: LLMEndpointConfig(
                    url      = ep.url,
                    model    = ep.model,
                    type     = ep.type,
                    provider = ep.provider,
                )
                for alias, ep in registry.llm_endpoints.items()
            }
        except Exception:
            endpoints = _DEFAULT_ENDPOINTS
    else:
        endpoints = _DEFAULT_ENDPOINTS

    return VaultConfig(
        vault_paths   = VaultPaths(vault_root=project_root / "knowledge-base"),
        system_paths  = SystemPaths(project_root=project_root),
        llm_endpoints = endpoints,
    )
