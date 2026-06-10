"""Vault configuration structure.

Dataclasses only — no loading logic, no I/O.
Loader lives in shared.loaders (implementation layer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LLMEndpointConfig:
    url:      str
    model:    str
    type:     str      # "vision" | "text"
    provider: str


@dataclass(frozen=True)
class VaultPaths:
    """Derived path accessors from a single vault_root."""
    vault_root:   Path

    @property
    def inbox(self) -> Path:
        return self.vault_root / "00-Inbox"

    @property
    def processing(self) -> Path:
        return self.vault_root / "01-Processing"

    @property
    def library(self) -> Path:
        return self.vault_root / "02-Library"

    @property
    def campaigns(self) -> Path:
        return self.vault_root / "03-Campaigns"

    @property
    def relationships(self) -> Path:
        return self.vault_root / "04-Relationships"

    @property
    def assets(self) -> Path:
        return self.vault_root / "05-Assets"

    @property
    def archive(self) -> Path:
        return self.vault_root / "99-Archive"


@dataclass(frozen=True)
class SystemPaths:
    """Derived path accessors from a single project_root."""
    project_root: Path

    @property
    def agents_dir(self) -> Path:
        return self.project_root / ".agents"

    @property
    def shared_state(self) -> Path:
        return self.project_root / ".shared" / "state"

    @property
    def logs_dir(self) -> Path:
        return self.agents_dir / "runtime" / "state" / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.agents_dir / "review" / "state" / "reports"

    def agent_state(self, agent_name: str) -> Path:
        return self.agents_dir / agent_name / "state"


@dataclass(frozen=True)
class VaultConfig:
    vault_paths:   VaultPaths
    system_paths:  SystemPaths
    llm_endpoints: dict[str, LLMEndpointConfig] = field(default_factory=dict)
