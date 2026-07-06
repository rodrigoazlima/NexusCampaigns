"""Quality gate implementation.

Scoring formula (+2 each, max 10):
  - description_section  : ## Description (or ## Descrição) present in body
  - has_wikilinks        : at least one [[link]] in relationships or body
  - enough_tags          : >= 3 tags in frontmatter
  - type_set             : type field present and non-empty
  - source_set           : at least one source entry

Library promotion requires: quality >= 7, reviewed=True, relationships non-empty.
"""

from __future__ import annotations

import re

from .interfaces import IQualityGate


_DESCRIPTION_HEADING = re.compile(
    r"^##\s+(description|descrição|desc)\b",
    re.IGNORECASE | re.MULTILINE,
)
_WIKILINK = re.compile(r"\[\[.+?\]\]")


class QualityGate(IQualityGate):
    """Stateless quality gate. Thread-safe."""

    def score(self, frontmatter: dict, body: str) -> int:
        points = 0

        if _DESCRIPTION_HEADING.search(body):
            points += 2

        relationships = frontmatter.get("relationships") or []
        body_links = _WIKILINK.findall(body)
        if relationships or body_links:
            points += 2

        tags = frontmatter.get("tags") or []
        if len(tags) >= 3:
            points += 2

        if frontmatter.get("type"):
            points += 2

        sources = frontmatter.get("source") or []
        if sources:
            points += 2

        return min(points, 10)

    def is_library_ready(self, frontmatter: dict) -> bool:
        quality = frontmatter.get("quality", 0)
        reviewed = frontmatter.get("reviewed", False)
        relationships = frontmatter.get("relationships") or []
        return quality >= 7 and reviewed is True and len(relationships) > 0
