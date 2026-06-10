"""Slug and wikilink utilities shared across pipeline agents.

All functions are pure — no I/O, no side effects.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+?)(?:[|#][^\[\]]*)?\]\]")
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MULTI_DASH_RE = re.compile(r"-{2,}")


def to_slug(text: str) -> str:
    """Convert arbitrary text to a lowercase hyphenated slug.

    >>> to_slug("Black Hollow Cemetery")
    'black-hollow-cemetery'
    >>> to_slug("Père Noël (Evil)")
    'pere-noel-evil'
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower()
    slugified = _NON_SLUG_RE.sub("-", lower)
    return _MULTI_DASH_RE.sub("-", slugified).strip("-")


def entity_id_from_path(path: Path) -> str:
    """Return the entity id (filename stem) from a vault .md path.

    >>> entity_id_from_path(Path("02-Library/npc-necromancer.md"))
    'npc-necromancer'
    """
    return path.stem


def normalize_slug(path: Path) -> str:
    """Alias for entity_id_from_path — explicit intent signal for wikilink code."""
    return path.stem


def extract_wikilinks(text: str) -> list[str]:
    """Return all [[target]] slugs found in text (deduped, insertion-ordered).

    Handles [[link]], [[link|alias]], [[link#heading]] forms.
    Returns the target part only (before | or #).

    >>> extract_wikilinks("See [[npc-witch]] and [[location-swamp|The Swamp]].")
    ['npc-witch', 'location-swamp']
    """
    seen: dict[str, None] = {}
    for m in _WIKILINK_RE.finditer(text):
        slug = m.group(1).strip()
        if slug:
            seen[slug] = None
    return list(seen)


def wikilink(slug: str) -> str:
    """Format a slug as a wikilink string.

    >>> wikilink("npc-witch")
    '[[npc-witch]]'
    """
    return f"[[{slug}]]"


def has_wikilink(text: str, slug: str) -> bool:
    """Return True if text already contains [[slug]] (any alias/heading variant)."""
    pattern = re.compile(
        r"\[\[" + re.escape(slug) + r"(?:[|#][^\[\]]*)?\]\]",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def slugs_from_relationships(relationships: list[str]) -> list[str]:
    """Extract slug strings from a list of relationship wikilink strings.

    >>> slugs_from_relationships(["[[npc-witch]]", "[[location-swamp|Swamp]]"])
    ['npc-witch', 'location-swamp']
    """
    result: list[str] = []
    for entry in relationships:
        found = extract_wikilinks(entry)
        result.extend(found)
    return result
