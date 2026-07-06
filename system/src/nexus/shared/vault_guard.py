"""Concrete VaultGuard — implements IVaultGuard.

Enforces write-protection rules from security.spec.md:
  - Agents may NOT write to 02-Library/ (human promotion only)
  - Agents may NOT delete files from 00-Inbox/ (source preservation)
  - Agents may NOT set reviewed=True or status='approved' in frontmatter (G3)

Note: Ingestion Agent renames files within 00-Inbox/ — it does NOT call
assert_writable() because renaming is an explicit responsibility defined in
its AGENT.md. VaultGuard is for agents writing new content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import VaultPaths
from .interfaces import IVaultGuard, VaultWriteError

# Frontmatter fields that only humans may set to their protected values.
_HUMAN_ONLY_FIELDS: dict[str, Any] = {
    "reviewed": True,
    "status":   "approved",
}


class VaultGuard(IVaultGuard):
    """Enforces vault security constraints on file operations."""

    def __init__(self, vault_paths: VaultPaths) -> None:
        self._library = vault_paths.library.resolve()
        self._inbox   = vault_paths.inbox.resolve()

    def assert_writable(self, target: Path) -> None:
        resolved = target.resolve()
        if _is_under(resolved, self._library):
            raise VaultWriteError(
                f"Agents may not write directly to 02-Library/: {target}"
            )
        if _is_under(resolved, self._inbox):
            raise VaultWriteError(
                f"Agents may not create new files in 00-Inbox/: {target}"
            )

    def assert_not_inbox_delete(self, target: Path) -> None:
        resolved = target.resolve()
        if _is_under(resolved, self._inbox):
            raise VaultWriteError(
                f"Agents may not delete files from 00-Inbox/: {target}"
            )

    def assert_not_self_approved(self, frontmatter: dict) -> None:
        for field, forbidden_value in _HUMAN_ONLY_FIELDS.items():
            if frontmatter.get(field) == forbidden_value:
                raise VaultWriteError(
                    f"Agents may not set {field}={forbidden_value!r} "
                    f"— human-only field (security.spec.md G3)"
                )


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
