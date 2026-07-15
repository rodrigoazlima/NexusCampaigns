"""classification.tools.enrich_tags

Actions: EnrichTags · InferType · FlagDuplicates
Reads:   00-Inbox/**/*.md, 01-Processing/**/*.md, system/state/inbox-queue.json
Writes:  enriched frontmatter in-place (never 02-Library/)
LLM:     LocalRouter http://localhost:8080 (openai-compat, model=auto)
"""

from __future__ import annotations

import json as _json
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from nexus.shared import (  # noqa: E402
    FrontmatterIO,
    LLMClient,
    LLMOfflineError,
    LLMResponseError,
    Logger,
    TagEnrichmentOutput,
    VaultWriteError,
    locked_update_queue_entry,
)
from nexus.shared.config import LLMEndpointConfig  # noqa: E402
from nexus.shared.loaders import load_llm_endpoint  # noqa: E402

TASK_ID         = "classification-agent"
SCRIPT_BASENAME = "enrich_tags.py"
BATCH_SIZE      = 20

_VAULT_ROOT   = _PROJECT_ROOT / ".knowledge-base"
_INBOX        = _VAULT_ROOT / "00-Inbox"
_PROCESSING   = _VAULT_ROOT / "01-Processing"
_LIBRARY      = _VAULT_ROOT / "02-Library"
_AGENT_STATE  = _AGENTS_DIR / "classification" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_MASTER_LOG   = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_BAD_DOCS     = _AGENT_STATE / "bad-docs.txt"
_PROMPT_FILE  = _AGENTS_DIR / "classification" / "prompts" / "enrich-tags.txt"
_SHARED_STATE = _PROJECT_ROOT / "system" / "state"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"

_TAG_LIBRARY_FILE = _AGENT_STATE / "tag-library.json"

# Tags are no longer filtered against a fixed vocabulary — the LLM proposes
# freely and _canonicalize_tag() folds variants into whichever spelling was
# seen first (state/tag-library.json), so "elf" stays "elf" even if a later
# note's model says "elven".
_ALLOWED_TYPES: frozenset[str] = frozenset({
    "npc", "character", "faction", "location", "city", "village", "dungeon",
    "item", "artifact", "quest", "encounter", "creature", "monster", "event",
    "religion", "organization", "timeline", "lore",
})

_LLM_CFG = load_llm_endpoint(
    "local_router",
    fallback = LLMEndpointConfig(
        url      = "http://localhost:8080/v1/chat/completions",
        model    = "auto",
        type     = "text",
        provider = "lmstudio",
    ),
    agent_dir    = _AGENTS_DIR / "classification",
    task_id      = TASK_ID,
    project_root = _PROJECT_ROOT,
)

# Minimum difflib ratio to flag a slug as similar-to a library slug
_SIMILARITY_THRESHOLD = 0.85

# Types the vision agent assigns as placeholder defaults (portrait→npc, battlemap→location).
# These are safe to refine — a more specific type should be inferred from content.
_VISION_DEFAULTS: frozenset[str] = frozenset({"npc", "location"})

# Vision image-type tags → plausible entity types (used to build prompt hint)
_IMAGE_TYPE_HINTS: dict[str, list[str]] = {
    "portrait":  ["npc", "character", "creature", "monster"],
    "body":      ["npc", "character", "creature", "monster"],
    "token":     ["npc", "character", "creature", "monster"],
    "battlemap": ["location", "dungeon", "encounter"],
    "scene":     ["location", "dungeon", "event", "encounter"],
}

_TYPE_PROMPT = (
    "Return ONLY valid JSON with the entity type for this RPG note.\n"
    "Allowed types: npc, character, faction, location, city, village, dungeon, "
    "item, artifact, quest, encounter, creature, monster, event, religion, "
    "organization, timeline, lore\n"
    "Prefer specific types: dungeon over location for tombs/caves, "
    "creature over npc for monsters, artifact over item for relics.\n"
    "Format: {{\"type\": \"<value_or_null>\"}}\n\n"
    "Title: {title}\n{image_hint}Content: {content}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_logger() -> Logger:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _MASTER_LOG.parent.mkdir(parents=True, exist_ok=True)
    return Logger(TASK_ID, SCRIPT_BASENAME, _LOGS_DIR, _MASTER_LOG)


def _load_bad_docs() -> set[str]:
    if not _BAD_DOCS.exists():
        return set()
    return {
        ln.strip()
        for ln in _BAD_DOCS.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }


def _append_bad(rel: str) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    with open(_BAD_DOCS, "a", encoding="utf-8") as fh:
        fh.write(rel + "\n")


def _library_slugs() -> set[str]:
    if not _LIBRARY.is_dir():
        return set()
    return {p.stem.lower() for p in _LIBRARY.glob("**/*.md")}


def _candidate_files(bad_docs: set[str], *, limit: int = 0) -> list[Path]:
    """Return .md files from Inbox and Processing, excluding bad-docs. limit=0 means no cap."""
    paths: list[Path] = []
    for root in (_INBOX, _PROCESSING):
        if root.is_dir():
            for p in sorted(root.glob("**/*.md")):
                if ".git" not in p.parts and "agents" not in p.parts:
                    rel = p.relative_to(_PROJECT_ROOT).as_posix()
                    if rel not in bad_docs:
                        paths.append(p)
    return paths[:limit] if limit > 0 else paths


def _assert_not_library(path: Path) -> None:
    """Raise VaultWriteError if path is inside 02-Library/."""
    try:
        path.resolve().relative_to(_LIBRARY.resolve())
        raise VaultWriteError(f"Agents may not modify 02-Library/: {path}")
    except ValueError:
        pass  # not under library — safe to write


def _write_with_retry(
    path: Path,
    fm: dict,
    body: str,
    fio: FrontmatterIO,
    retries: int = 5,
) -> bool:
    _assert_not_library(path)
    for attempt in range(retries):
        try:
            fio.write(path, fm, body)
            return True
        except Exception:
            if attempt < retries - 1:
                time.sleep(0.3)
    return False


def _load_prompt_template() -> str:
    if _PROMPT_FILE.exists():
        return _PROMPT_FILE.read_text(encoding="utf-8")
    return 'Tag this note. Return JSON: {"tags": [], "type": null}'


def _slug_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# Tag library — canonicalizes free-form LLM tags instead of a fixed vocabulary
# ---------------------------------------------------------------------------

def _load_tag_library() -> dict[str, Any]:
    if not _TAG_LIBRARY_FILE.exists():
        return {"version": 1, "tags": {}}
    return _json.loads(_TAG_LIBRARY_FILE.read_text(encoding="utf-8"))


def _save_tag_library(library: dict[str, Any]) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _TAG_LIBRARY_FILE.with_suffix(".tmp")
    tmp.write_text(_json.dumps(library, indent=2, default=str), encoding="utf-8")
    tmp.replace(_TAG_LIBRARY_FILE)


def _canonicalize_tag(raw: str, library: dict[str, Any]) -> str:
    """Fold a free-form tag into whichever spelling was registered first.

    Exact match reuses the existing entry. Otherwise fuzzy-matches against
    every known tag (ponytail: O(n) scan — fine at hundreds of tags, add an
    index if the library grows into the thousands) and folds into the best
    match above _SIMILARITY_THRESHOLD, recording the raw spelling as an
    alias. No match at all registers `raw` as a brand-new canonical tag.
    """
    norm = raw.strip().lower()
    if not norm:
        return ""

    tags = library.setdefault("tags", {})
    now = datetime.now(timezone.utc).isoformat()

    if norm in tags:
        tags[norm]["count"] += 1
        return norm

    best_key, best_score = None, 0.0
    for key in tags:
        score = _slug_similarity(norm, key)
        if score > best_score:
            best_key, best_score = key, score

    if best_key is not None and best_score >= _SIMILARITY_THRESHOLD:
        entry = tags[best_key]
        entry["count"] += 1
        if norm not in entry["aliases"]:
            entry["aliases"].append(norm)
        return best_key

    tags[norm] = {"createdAt": now, "count": 1, "aliases": []}
    return norm


def _image_hint(tags: list[str]) -> str:
    """Return a prompt hint line when tags contain a vision image-type, else empty string."""
    for tag in tags:
        candidates = _IMAGE_TYPE_HINTS.get(tag)
        if candidates:
            return f"Image classified as '{tag}' — likely entity types: {', '.join(candidates)}.\n"
    return ""


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

def _load_queue() -> dict[str, Any]:
    """Load inbox-queue.json; returns empty dict if missing or unparseable."""
    if not _QUEUE_FILE.exists():
        return {}
    try:
        return _json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_queue_done(queue: dict[str, Any], rel: str) -> bool:
    """Return True if the file's classification slot is already done or skip."""
    entry = queue.get(rel)
    if entry is None:
        return False
    agents = entry.get("agents")
    if not isinstance(agents, dict):
        return False
    return agents.get("classification") in ("done", "skip")


def _mark_classification_done(entry: dict) -> Optional[str]:
    agents = entry.get("agents")
    if isinstance(agents, dict) and agents.get("classification") == "pending":
        agents["classification"] = "done"
    return None


def _mark_queue_done(queue: dict[str, Any], rel: str) -> None:
    """Mark classification slot done for rel — locked, fresh, one entry at a time.

    rel may be an .md path (01-Processing/) or a direct inbox image path.
    For .md files, also marks the source image's queue entry done via
    the frontmatter 'source' field. `queue` is only consulted (not mutated)
    to decide which keys exist — the actual write reloads fresh under lock.
    """
    if rel in queue:
        locked_update_queue_entry(_QUEUE_FILE, rel, _mark_classification_done)

    # Indirect: rel is a .md file; trace back to source image via frontmatter
    md_path = _PROJECT_ROOT / rel
    if md_path.suffix == ".md" and md_path.exists():
        try:
            fm, _ = FrontmatterIO().read(md_path)
            for src in fm.get("source") or []:
                if src in queue:
                    locked_update_queue_entry(_QUEUE_FILE, src, _mark_classification_done)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# EnrichTags action — core loop
# ---------------------------------------------------------------------------

def _run_enrich_tags() -> tuple[int, int]:
    """EnrichTags + InferType in one LLM call per sparse file. Returns (count, failed)."""
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log = _make_logger()
        log.warning("LocalRouter (localhost:8080) offline — skipping batch")
        return 0, 0

    bad_docs   = _load_bad_docs()
    queue      = _load_queue()
    fio        = FrontmatterIO()
    prompt_tpl = _load_prompt_template()
    count      = 0
    failed     = 0
    log        = _make_logger()

    for md_path in _candidate_files(bad_docs, limit=BATCH_SIZE):
        rel = md_path.relative_to(_PROJECT_ROOT).as_posix()

        if _is_queue_done(queue, rel):
            continue

        try:
            fm, body = fio.read(md_path)
        except Exception as exc:
            log.warning(f"Parse error {md_path.name}: {exc}")
            _append_bad(rel)
            failed += 1
            continue

        existing_tags = fm.get("tags") or []
        current_type  = fm.get("type") or ""
        needs_tags    = len(existing_tags) <= 2
        # Allow refinement when vision agent wrote a placeholder default type
        # (portrait→npc, battlemap→location) and human hasn't reviewed yet.
        is_vision_default = current_type in _VISION_DEFAULTS and not fm.get("reviewed")
        needs_type    = not current_type or is_vision_default

        if not needs_tags and not needs_type:
            _mark_queue_done(queue, rel)
            count += 1
            continue

        title   = fm.get("id") or md_path.stem
        excerpt = body[:500]
        hint    = _image_hint(existing_tags)
        prompt  = (
            prompt_tpl
            .replace("{title}", title)
            .replace("{current_tags}", ", ".join(existing_tags) if existing_tags else "none")
            .replace("{image_hint}", hint)
            .replace("{content}", excerpt)
        )

        try:
            raw        = client.chat([{"role": "user", "content": prompt}], max_tokens=80)
            if not raw or not raw.strip():
                log.warning(f"Empty LLM response for {md_path.name} — skipping (transient)")
                time.sleep(0.3)
                continue
            enrichment = TagEnrichmentOutput.model_validate(_json.loads(raw))
        except LLMOfflineError:
            log.warning("LLM offline — aborting batch")
            break
        except (LLMResponseError, _json.JSONDecodeError) as exc:
            log.warning(f"LLM response error for {md_path.name}: {exc} — skipping (transient)")
            time.sleep(0.3)
            continue
        except Exception as exc:
            log.error(f"LLM error for {md_path.name}: {exc}")
            _append_bad(rel)
            failed += 1
            time.sleep(0.3)
            continue

        changed = False

        if needs_tags and enrichment.tags:
            valid_new = [
                t for t in enrichment.tags
                if t in _ALLOWED_TAGS and t not in existing_tags
            ]
            if valid_new:
                fm["tags"] = list(existing_tags) + valid_new
                changed = True

        if needs_type and enrichment.type and enrichment.type in _ALLOWED_TYPES:
            if enrichment.type != current_type:
                fm["type"] = enrichment.type
                changed = True

        if changed:
            ok = _write_with_retry(md_path, fm, body, fio)
            if ok:
                log.info(f"Enriched: {md_path.name} tags={fm.get('tags')} type={fm.get('type')}")
                _mark_queue_done(queue, rel)
                count += 1
            else:
                log.error(f"Write failed: {md_path.name}")
                failed += 1
        else:
            _mark_queue_done(queue, rel)
            count += 1

        time.sleep(0.3)

    return count, failed


def main() -> None:
    """EnrichTags entry point — called when run as a CLI script."""
    log = _make_logger()
    t0  = log.start()
    count, failed = _run_enrich_tags()
    log.done(t0, key="classified", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


# ---------------------------------------------------------------------------
# InferType action — type-only pass (targeted)
# ---------------------------------------------------------------------------

def _run_infer_type() -> tuple[int, int]:
    """InferType: process only files with missing type field (max_tokens=10)."""
    log    = _make_logger()
    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("LocalRouter offline — InferType skipped")
        return 0, 0

    bad_docs = _load_bad_docs()
    fio      = FrontmatterIO()
    count    = 0
    failed   = 0

    for md_path in _candidate_files(bad_docs):
        try:
            fm, body = fio.read(md_path)
        except Exception:
            continue

        current_type = fm.get("type") or ""
        is_vision_default = current_type in _VISION_DEFAULTS and not fm.get("reviewed")
        if current_type and not is_vision_default:
            continue

        tags    = fm.get("tags") or []
        title   = fm.get("id") or md_path.stem
        excerpt = body[:300]
        hint    = _image_hint(tags)
        prompt  = (
            _TYPE_PROMPT
            .replace("{title}", title)
            .replace("{image_hint}", hint)
            .replace("{content}", excerpt)
        )

        try:
            raw           = client.chat([{"role": "user", "content": prompt}], max_tokens=10)
            inferred_type = _json.loads(raw).get("type")
        except LLMOfflineError:
            log.warning("LLM offline — aborting InferType")
            break
        except Exception as exc:
            log.error(f"InferType LLM error for {md_path.name}: {exc}")
            failed += 1
            time.sleep(0.3)
            continue

        if inferred_type and inferred_type in _ALLOWED_TYPES and inferred_type != current_type:
            fm["type"] = inferred_type
            ok = _write_with_retry(md_path, fm, body, fio)
            if ok:
                log.info(f"InferType: {md_path.name} {current_type or 'none'} → {inferred_type}")
                count += 1
            else:
                log.error(f"Write failed (InferType): {md_path.name}")
                failed += 1

        time.sleep(0.3)

    return count, failed


# ---------------------------------------------------------------------------
# FlagDuplicates action — exact + similarity-based slug comparison
# ---------------------------------------------------------------------------

def _run_flag_duplicates() -> int:
    """FlagDuplicates: exact slug match then difflib similarity against 02-Library/."""
    lib_slugs = _library_slugs()
    if not lib_slugs:
        return 0

    fio     = FrontmatterIO()
    flagged = 0

    for scope in (_INBOX, _PROCESSING):
        if not scope.is_dir():
            continue
        for md_path in sorted(scope.glob("**/*.md")):
            try:
                fm, body = fio.read(md_path)
            except Exception:
                continue

            doc_slug = (fm.get("id") or md_path.stem).lower()
            if not doc_slug:
                continue

            # Exact match takes priority
            if doc_slug in lib_slugs:
                if fm.get("duplicate_of") != doc_slug:
                    fm["duplicate_of"] = doc_slug
                    try:
                        _write_with_retry(md_path, fm, body, fio)
                        flagged += 1
                    except VaultWriteError:
                        pass
                continue

            # Similarity-based: flag near-duplicates
            best_slug  = max(lib_slugs, key=lambda s: _slug_similarity(doc_slug, s))
            best_score = _slug_similarity(doc_slug, best_slug)
            if best_score >= _SIMILARITY_THRESHOLD:
                sim_value = f"similar_to:{best_slug}({best_score:.2f})"
                if fm.get("duplicate_of") != sim_value:
                    fm["duplicate_of"] = sim_value
                    try:
                        _write_with_retry(md_path, fm, body, fio)
                        flagged += 1
                    except VaultWriteError:
                        pass

    return flagged


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from nexus.shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "enrich_tags",
        "description": (
            "Process notes in 00-Inbox/ and 01-Processing/ that have ≤5 tags or a missing "
            "type field. Calls LocalRouter LLM to suggest DM-domain tags and infer entity "
            "type in one pass. Updates inbox-queue.json classification slot to done. "
            "Returns count of enriched files."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "infer_type",
        "description": (
            "Targeted pass: process only notes with a missing type field. "
            "Uses a shorter prompt (max_tokens=10) for efficient type inference. "
            "Call when enrich_tags has already handled tags but type is still missing."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "flag_duplicates",
        "description": (
            "Scan 00-Inbox/ and 01-Processing/ for entities whose slug exactly matches "
            "or is highly similar (≥0.85 difflib ratio) to a 02-Library/ slug. "
            "Sets duplicate_of field in frontmatter. Returns count flagged."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    if name == "enrich_tags":
        count, failed = _run_enrich_tags()
        return f"EnrichTags complete: enriched={count} failed={failed}"

    if name == "infer_type":
        count, failed = _run_infer_type()
        return f"InferType complete: inferred={count} failed={failed}"

    if name == "flag_duplicates":
        flagged = _run_flag_duplicates()
        return f"FlagDuplicates complete: flagged={flagged}"

    raise ValueError(f"Unknown tool: {name!r}")


if __name__ == "__main__":
    main()
