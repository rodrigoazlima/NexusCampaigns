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

# Forbidden substrings / patterns in entity slugs (data-contracts.spec.md)
_FORBIDDEN_SLUG_SUBSTRINGS: frozenset[str] = frozenset({
    "final_v2", "new", "cool", "untitled",
})
_VALID_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")


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


def build_entity_slug(entity_type: str, *descriptors: str) -> str:
    """Build a spec-compliant entity slug: {type}-{descriptor1}-{descriptor2}.

    Each part is individually slugified and joined with hyphens.

    >>> build_entity_slug("npc", "Necromancer", "Black Hollow")
    'npc-necromancer-black-hollow'
    >>> build_entity_slug("location", "Dungeon Cirit 01")
    'location-dungeon-cirit-01'
    """
    parts = [to_slug(entity_type)] + [to_slug(d) for d in descriptors if d]
    return "-".join(p for p in parts if p)


def is_valid_slug(slug: str) -> bool:
    """Return True if slug follows the data-contracts spec naming rules.

    Rules:
    - Lowercase letters, digits, and hyphens only
    - Must start with a letter
    - Must contain at least one hyphen (type prefix required)
    - No forbidden substrings: final_v2, new, cool, untitled
    - No uppercase, no spaces, no underscores

    >>> is_valid_slug("npc-necromancer-black-hollow")
    True
    >>> is_valid_slug("Untitled")
    False
    >>> is_valid_slug("npc_new")
    False
    >>> is_valid_slug("final_v2-boss")
    False
    """
    lower = slug.lower()
    if any(forbidden in lower for forbidden in _FORBIDDEN_SLUG_SUBSTRINGS):
        return False
    # Reject uppercase, spaces, underscores
    if slug != lower or " " in slug or "_" in slug:
        return False
    return bool(_VALID_SLUG_RE.match(slug))


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
