"""Concrete VaultGuard — implements IVaultGuard.

Enforces write-protection rules from security.spec.md:
  - Agents may NOT write to 02-Library/ (human promotion only)
  - Agents may NOT delete files from 00-Inbox/ (source preservation)

Note: Ingestion Agent renames files within 00-Inbox/ — it does NOT call
assert_writable() because renaming is an explicit responsibility defined in
its AGENT.md. VaultGuard is for agents writing new content.
"""

from __future__ import annotations

from pathlib import Path

from .config import VaultPaths
from .interfaces import IVaultGuard, VaultWriteError


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


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
