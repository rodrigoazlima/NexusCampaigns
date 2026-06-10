"""Entity scanner — enumerate vault entities with parsed frontmatter.

Shared by review, curator, canon, relationship, search, and deduplication agents.
All scanning is read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .interfaces import IFrontmatterIO
from .models import EntityFrontmatter


class EntityScanner:
    """Walk one or more vault directories and yield parsed entity records."""

    def __init__(self, fio: IFrontmatterIO) -> None:
        self._fio = fio

    def scan(
        self,
        *dirs: Path,
        recursive: bool = True,
    ) -> Iterator[tuple[Path, EntityFrontmatter, str]]:
        """Yield (path, frontmatter, body) for every parseable .md file.

        Files whose frontmatter cannot be validated as EntityFrontmatter are
        silently skipped — callers get only well-formed records.

        Args:
            *dirs: One or more vault directories to scan.
            recursive: If True, recurse into subdirectories (default True).
        """
        glob_pattern = "**/*.md" if recursive else "*.md"
        for vault_dir in dirs:
            if not vault_dir.is_dir():
                continue
            for md_path in sorted(vault_dir.glob(glob_pattern)):
                try:
                    fm_dict, body = self._fio.read(md_path)
                    fm = EntityFrontmatter.model_validate(fm_dict)
                    yield md_path, fm, body
                except Exception:
                    continue

    def scan_ids(self, *dirs: Path) -> dict[str, Path]:
        """Return {entity_id: path} index for all parseable entities."""
        return {fm.id: path for path, fm, _ in self.scan(*dirs)}

    def scan_slugs(self, *dirs: Path) -> dict[str, Path]:
        """Return {filename_stem: path} index for wikilink resolution."""
        return {path.stem: path for path, _, _ in self.scan(*dirs)}

    def count(self, *dirs: Path) -> int:
        """Return total parseable entity count across all dirs."""
        return sum(1 for _ in self.scan(*dirs))
