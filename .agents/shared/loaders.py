"""Config loader — builds VaultConfig from project root.

config.py declares the structure; this module resolves it from disk.

Auto-discovery: walks up from __file__ until finding a directory that
contains knowledge-base/. Explicit root overrides auto-detect.

Default LLM endpoints match llm-integration.spec.md:
  vision/lore  → localhost:1234  (Qwen3-VL)
  classification → localhost:8080 (unspecified model)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths


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


def load_vault_config(project_root: Optional[Path] = None) -> VaultConfig:
    """Build a VaultConfig for the current project.

    Args:
        project_root: Explicit project root. Auto-detects if None.
    """
    if project_root is None:
        project_root = _find_project_root(Path(__file__).resolve().parent)

    return VaultConfig(
        vault_paths   = VaultPaths(vault_root=project_root / "knowledge-base"),
        system_paths  = SystemPaths(project_root=project_root),
        llm_endpoints = _DEFAULT_ENDPOINTS,
    )
