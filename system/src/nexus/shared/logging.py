"""nexus.shared.logging - structured tag suffixes for any log line.

Every pipeline stage used to format its own ad hoc mix of identifiers in log
messages - some logged a truncated hash, most logged only a filename, none
logged uuid, no two stages agreed on a format. That made anything (an image,
an NPC, a scenario) nearly impossible to trace by grep alone - see
docs/investigate for a case that only got explained by manually re-hashing
files by hand instead of grepping automation.log.

`tag()` is the one place the 'trailing structured suffix' format is decided;
`image_tag()` is a thin convenience wrapper over it for the image pipeline's
common fields (hash/uuid/path). Append either to any log message concerning
a specific entity so it's grep-able by any of its identifiers across every
worker/agent's log output:

    log.info(f"Classified: {img_path.name}{image_tag(sha256=sha, uuid=note_uuid, path=rel)}")
    # -> "Classified: sword.webp [hash=91ce4f0a6080 uuid=8f762e6c-... path=00-Inbox/images/sword.webp]"

    log.info(f"Linked scenario{tag(scenario=scenario_id, entity=slug)}")
    # -> "Linked scenario [scenario=a2-cirit entity=npc-necromancer]"
"""

from __future__ import annotations

from typing import Any, Optional

HASH_DISPLAY_LEN = 12


def tag(**fields: Any) -> str:
    """Build a trailing ' [key=value ...]' suffix from arbitrary fields.

    Any field whose value is None or empty is omitted. Field order follows
    call-site keyword order.
    """
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "")]
    return f" [{' '.join(parts)}]" if parts else ""


def image_tag(
    *,
    sha256: Optional[str] = None,
    uuid: Optional[str] = None,
    path: Optional[str] = None,
    **extra: Any,
) -> str:
    """`tag()` for the image pipeline's common fields.

    Hash is truncated to HASH_DISPLAY_LEN hex chars - enough to grep for; the
    full hash is always recoverable from frontmatter/state for exact
    verification. Extra keyword fields (e.g. scenario=...) pass through to
    tag() and are appended after hash/uuid/path.
    """
    fields: dict[str, Any] = {}
    if sha256:
        fields["hash"] = sha256[:HASH_DISPLAY_LEN]
    if uuid:
        fields["uuid"] = uuid
    if path:
        fields["path"] = path
    fields.update(extra)
    return tag(**fields)
