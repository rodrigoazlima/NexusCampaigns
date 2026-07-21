"""nexus.shared.tag_refinement - refine_tags_with_library().

Extracted out of the vision agent (now externally hosted at
https://github.com/rodrigoazlima/nc-vision-agent, no longer importable
in-process) so classification-agent's image-grounded "second opinion" tag
refinement doesn't depend on another agent's code - each agent must stand
alone; shared logic lives here instead. vision-agent keeps its own internal
copy of this same step as part of its own multi-cycle conversation; this
module is classification's independent path to the same capability.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .interfaces import LLMOfflineError
from .llm_client import _resize_and_encode, _strip_code_fence
from .models import EntityType

_VISION_SYSTEM_PROMPT = "You are a Pathfinder 2e image classifier. Return ONLY valid JSON."
_MAX_TAG_WORDS = 6
_ENTITY_TYPES = frozenset(e.value for e in EntityType)


def is_concrete_tag(tag: str) -> bool:
    """Reject sentence-length strings an LLM sometimes returns instead of a
    short tag - keeps frontmatter `tags:` scannable rather than carrying
    paragraph-length prose."""
    return bool(tag) and 1 <= len(tag.split()) <= _MAX_TAG_WORDS


def image_content_block(img_path: Path) -> dict:
    b64 = _resize_and_encode(img_path)
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def _refine_prompt(current_tags: list[str], known_tags: list[str], entity_type_hint: str, min_tags_target: int) -> str:
    return (
        "Here is our tag library - canonical tags already in use elsewhere in "
        f"this knowledge base: {', '.join(known_tags) or 'none yet'}\n\n"
        f"Our current tag list for this image: {', '.join(current_tags) or 'none'}\n\n"
        "Align these tags: where a known tag above means the same thing as one of "
        "ours, prefer the known spelling. Finalize the complete tag list for this "
        f"image (merge, dedupe, keep concrete and specific), aiming for at least "
        f"{min_tags_target} total if the image supports it. Confirm the entity "
        f"type (current best guess: {entity_type_hint}).\n\n"
        'Return ONLY valid JSON:\n{"final_tags": ["...", "..."], "entity_type": "..."}'
    )


def refine_tags_with_library(
    img_path: Path,
    client: Any,
    current_tags: list[str],
    entity_type_hint: str,
    library: dict[str, Any],
    *,
    history: Optional[list[dict]] = None,
    min_tags_target: int = 6,
    max_conversation_messages: int = 20,
    followup_max_tokens: int = 1024,
) -> tuple[list[str], str]:
    """Align current_tags against the tag library's known canonical tags and
    finalize tags + entity type, image still in context. Public/standalone-
    callable - pass history=None for a fresh conversation, or an existing
    message list to extend it in place."""
    known_tags = sorted(
        library.get("tags", {}),
        key=lambda t: -library["tags"][t].get("count", 0),
    )[:20]
    prompt_text = _refine_prompt(current_tags, known_tags, entity_type_hint, min_tags_target)

    if history is not None:
        messages = history
        messages.append({"role": "user", "content": prompt_text})
    else:
        messages = [
            {"role": "system", "content": _VISION_SYSTEM_PROMPT},
            {"role": "user", "content": [image_content_block(img_path), {"type": "text", "text": prompt_text}]},
        ]

    if len(messages) + 1 > max_conversation_messages:
        # Over budget even before this turn's reply - accept what we have
        # rather than exceed the message cap.
        return current_tags, entity_type_hint

    final_tags, entity_type = current_tags, entity_type_hint
    try:
        raw_text = client.chat(messages, max_tokens=followup_max_tokens)
        messages.append({"role": "assistant", "content": raw_text})
        resp = json.loads(_strip_code_fence(raw_text))
        candidate = resp.get("final_tags")
        if isinstance(candidate, list) and candidate:
            # Merge, never replace: a model that just repeats a subset of what
            # it was given (or rephrases "weapon" as "stylized sword") would
            # otherwise silently erase tags an earlier step already grounded
            # in the image's own visual analysis.
            merged = list(current_tags)
            for t in candidate:
                if isinstance(t, str) and t.strip():
                    norm = t.strip().lower()
                    if norm not in merged and is_concrete_tag(norm):
                        merged.append(norm)
            final_tags = merged
        et = resp.get("entity_type")
        if isinstance(et, str) and et in _ENTITY_TYPES:
            entity_type = et
    except LLMOfflineError:
        raise
    except Exception:
        pass  # graceful degrade - keep current_tags/entity_type_hint as-is

    return final_tags, entity_type
