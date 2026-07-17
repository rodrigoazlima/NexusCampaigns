You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.system/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.system/config/<script_name>.json`)
     - Contains script-specific settings and overrides.
     - Always loaded after global config (can override global values).
     - Can be empty (`{}`) but must always exist.

2. **Output Format:**
   - You must output **two valid JSON objects** clearly labeled.
   - Use sensible, descriptive keys in `snake_case`.
   - Include meaningful `default` values for every setting.
   - Add a `"description"` field for each major setting when helpful.
   - Group related settings under logical sections if needed.

3. **What to Extract:**
   - Hardcoded paths (especially those derived from `__file__`)
   - Constants (BATCH_SIZE, thresholds, limits, etc.)
   - LLM settings (URL, model, provider, etc.)
   - File/directory references
   - Magic numbers and strings that are likely to change
   - Any environment-dependent behavior

4. **Rules:**
   - Prefer putting common things (project roots, LLM config, logging, shared directories) in **global**.
   - Put script-specific behavior (batch sizes, task-specific prompts, agent name, etc.) in **local**.
   - Make sure the JSONs contain good defaults so the script works even if the files are deleted.
   - Use clear, consistent naming.
   - Do not include code - only configuration.

---

**Script to analyze:**

# classification\tools\enrich_tags.py
"""classification.tools.enrich_tags

Actions: EnrichTags · InferType · FlagDuplicates
Reads:   00-Inbox/**/*.md, 01-Processing/**/*.md
Writes:  enriched frontmatter in-place (never 02-Library/)
LLM:     LocalRouter http://localhost:8080 (openai-compat, model=auto)
"""

from __future__ import annotations

import json as _json
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    FrontmatterIO,
    LLMClient,
    LLMOfflineError,
    LLMResponseError,
    Logger,
    TagEnrichmentOutput,
    VaultWriteError,
)
from shared.config import LLMEndpointConfig  # noqa: E402

TASK_ID         = "classification-agent"
SCRIPT_BASENAME = "enrich_tags.py"
BATCH_SIZE      = 20

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_INBOX       = _VAULT_ROOT / "00-Inbox"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_LIBRARY     = _VAULT_ROOT / "02-Library"
_AGENT_STATE = _AGENTS_DIR / "classification" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_BAD_DOCS    = _AGENT_STATE / "bad-docs.txt"
_PROMPT_FILE = _AGENTS_DIR / "classification" / "prompts" / "enrich-tags.txt"

_ALLOWED_TAGS: frozenset[str] = frozenset({
    "npc", "creature", "monster", "location", "dungeon", "city", "village",
    "faction", "quest", "encounter", "item", "artifact", "lore", "religion",
    "event", "organization", "timeline", "undead", "dark", "fire", "light",
    "none", "portrait", "battlemap", "scene", "token", "images", "pathfinder2e",
})
_ALLOWED_TYPES: frozenset[str] = frozenset({
    "npc", "character", "faction", "location", "city", "village", "dungeon",
    "item", "artifact", "quest", "encounter", "creature", "monster", "event",
    "religion", "organization", "timeline", "lore",
})

_LLM_CFG = LLMEndpointConfig(
    url      = "http://localhost:8080/v1/chat/completions",
    model    = "auto",
    type     = "text",
    provider = "lmstudio",
)

# Minimum difflib ratio to flag a slug as similar-to a library slug
_SIMILARITY_THRESHOLD = 0.85

_TYPE_PROMPT = (
    "Return ONLY valid JSON with the entity type for this RPG note.\n"
    "Allowed types: npc, character, faction, location, city, village, dungeon, "
    "item, artifact, quest, encounter, creature, monster, event, religion, "
    "organization, timeline, lore\n"
    "Format: {{\"type\": \"<value_or_null>\"}}\n\n"
    "Title: {title}\nContent: {content}"
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


def _candidate_files(bad_docs: set[str]) -> list[Path]:
    paths: list[Path] = []
    for root in (_INBOX, _PROCESSING):
        if root.is_dir():
            for p in sorted(root.glob("**/*.md")):
                if ".git" not in p.parts and ".agents" not in p.parts:
                    rel = p.relative_to(_PROJECT_ROOT).as_posix()
                    if rel not in bad_docs:
                        paths.append(p)
    return paths


def _assert_not_library(path: Path) -> None:
    """Raise VaultWriteError if path is inside 02-Library/."""
    try:
        path.resolve().relative_to(_LIBRARY.resolve())
        raise VaultWriteError(f"Agents may not modify 02-Library/: {path}")
    except ValueError:
        pass  # not under library - safe to write


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
# EnrichTags action - main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """EnrichTags + InferType in one LLM call per sparse file."""
    log = _make_logger()
    t0  = log.start()
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("LocalRouter (localhost:8080) offline - skipping batch")
        log.done(t0, key="classified", count=0, failed=0)
        sys.exit(0)

    bad_docs   = _load_bad_docs()
    fio        = FrontmatterIO()
    prompt_tpl = _load_prompt_template()
    count      = 0
    failed     = 0

    for md_path in _candidate_files(bad_docs):
        rel = md_path.relative_to(_PROJECT_ROOT).as_posix()

        try:
            fm, body = fio.read(md_path)
        except Exception as exc:
            log.warning(f"Parse error {md_path.name}: {exc}")
            _append_bad(rel)
            failed += 1
            continue

        existing_tags = fm.get("tags") or []
        has_type      = bool(fm.get("type"))
        needs_tags    = len(existing_tags) <= 5
        needs_type    = not has_type

        if not needs_tags and not needs_type:
            continue

        title   = fm.get("id") or md_path.stem
        excerpt = body[:500]
        prompt  = (
            prompt_tpl
            .replace("{title}", title)
            .replace("{current_tags}", ", ".join(existing_tags) if existing_tags else "none")
            .replace("{content}", excerpt)
        )

        try:
            raw        = client.chat([{"role": "user", "content": prompt}], max_tokens=80)
            enrichment = TagEnrichmentOutput.model_validate(_json.loads(raw))
        except LLMOfflineError:
            log.warning("LLM offline - aborting batch")
            break
        except (LLMResponseError, Exception) as exc:
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
            fm["type"] = enrichment.type
            changed = True

        if changed:
            ok = _write_with_retry(md_path, fm, body, fio)
            if ok:
                log.info(f"Enriched: {md_path.name} tags={fm.get('tags')} type={fm.get('type')}")
                count += 1
            else:
                log.error(f"Write failed: {md_path.name}")
                failed += 1
        else:
            count += 1

        time.sleep(0.3)

    log.done(t0, key="classified", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


# ---------------------------------------------------------------------------
# InferType action - type-only pass (targeted)
# ---------------------------------------------------------------------------

def _run_infer_type() -> tuple[int, int]:
    """InferType: process only files with missing type field (max_tokens=10)."""
    log    = _make_logger()
    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("LocalRouter offline - InferType skipped")
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

        if fm.get("type"):
            continue

        title   = fm.get("id") or md_path.stem
        excerpt = body[:300]
        prompt  = _TYPE_PROMPT.replace("{title}", title).replace("{content}", excerpt)

        try:
            raw           = client.chat([{"role": "user", "content": prompt}], max_tokens=10)
            inferred_type = _json.loads(raw).get("type")
        except LLMOfflineError:
            log.warning("LLM offline - aborting InferType")
            break
        except Exception as exc:
            log.error(f"InferType LLM error for {md_path.name}: {exc}")
            failed += 1
            time.sleep(0.3)
            continue

        if inferred_type and inferred_type in _ALLOWED_TYPES:
            fm["type"] = inferred_type
            ok = _write_with_retry(md_path, fm, body, fio)
            if ok:
                log.info(f"InferType: {md_path.name} type={inferred_type}")
                count += 1
            else:
                log.error(f"Write failed (InferType): {md_path.name}")
                failed += 1

        time.sleep(0.3)

    return count, failed


# ---------------------------------------------------------------------------
# FlagDuplicates action - exact + similarity-based slug comparison
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

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "enrich_tags",
        "description": (
            "Process notes in 00-Inbox/ and 01-Processing/ that have ≤5 tags or a missing "
            "type field. Calls LocalRouter LLM to suggest DM-domain tags and infer entity "
            "type in one pass. Returns count of enriched files."
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
        import contextlib
        import io as _io
        buf = _io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue() or "EnrichTags run complete"

    if name == "infer_type":
        count, failed = _run_infer_type()
        return f"InferType complete: inferred={count} failed={failed}"

    if name == "flag_duplicates":
        flagged = _run_flag_duplicates()
        return f"FlagDuplicates complete: flagged={flagged}"

    raise ValueError(f"Unknown tool: {name!r}")


if __name__ == "__main__":
    main()


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .system/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```

### Bonus: Loader Code Suggestion (for `shared/config.py`)

You can later create a simple loader like this:

```python
from pathlib import Path
import json

def load_config(script_path: Path):
    project_root = Path(__file__).resolve().parents[2]  # adjust as needed
    
    # Global
    global_path = project_root / "config" / "global.json"
    global_cfg = json.loads(global_path.read_text()) if global_path.exists() else {}
    
    # Local
    script_name = script_path.stem
    local_path = project_root / "config" / f"{script_name}.json"
    local_cfg = json.loads(local_path.read_text()) if local_path.exists() else {}
    
    # Merge (local overrides global)
    config = {**global_cfg, **local_cfg}
    return config
```

