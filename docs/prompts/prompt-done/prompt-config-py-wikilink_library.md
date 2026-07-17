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

# wikilink\tools\wikilink_library.py
"""wikilink.tools.wikilink_library

Actions: ScoreEntityPairs · InsertWikilinks
Reads:   02-Library/**/*.md, .agents/wikilink/state/wikilink-state.json
Writes:  ## Related sections in-place in 02-Library/ (body only, never frontmatter)
         .agents/wikilink/state/wikilink-state.json
No LLM. No 00-Inbox or 01-Processing writes.
Batch: 20 files per run.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    FrontmatterIO,
    Logger,
    StateStore,
    extract_wikilinks,
    has_wikilink,
    slugs_from_relationships,
    required_type_boost,
    WIKILINK_STATE_DEFAULT,
)
from shared.interfaces import IWikilinkResolver  # noqa: E402

TASK_ID         = "wikilink-agent"
SCRIPT_BASENAME = "wikilink_library.py"
BATCH_SIZE      = 20
MIN_SCORE       = 1   # minimum pair score to insert a link
MAX_LINKS       = 10  # max new links inserted per file per run

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_LIBRARY     = _VAULT_ROOT / "02-Library"
_AGENT_STATE = _AGENTS_DIR / "wikilink" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_STATE_FILE  = _AGENT_STATE / "wikilink-state.json"

_RELATED_HEADER_RE = re.compile(r"^## Related\s*$", re.MULTILINE)
_SECTION_RE        = re.compile(r"(## Related[ \t]*\n)(.*?)(?=\n## |\Z)", re.DOTALL)

_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could",
    "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "as", "into", "and", "or", "but", "not", "that", "this",
    "it", "its", "he", "she", "they", "his", "her", "their",
    "our", "we", "you", "i", "my", "your",
})


def _extract_keywords(text: str) -> frozenset[str]:
    """Extract significant lowercase words (min 4 chars, no stop words)."""
    return frozenset(
        w for w in re.findall(r"[a-z]{4,}", text.lower())
        if w not in _STOP_WORDS
    )


def _body_above_related(body: str) -> str:
    m = _RELATED_HEADER_RE.search(body)
    return body[: m.start()] if m else body


def _splice_related(body: str, new_slugs: list[str]) -> tuple[str, int]:
    """Insert [[slug]] lines into ## Related, creating the section if absent.

    Returns (updated_body, count_inserted).
    """
    inserted_count = 0

    def replacer(m: re.Match) -> str:
        nonlocal inserted_count
        header  = m.group(1)
        section = m.group(2)
        existing = set(extract_wikilinks(section))
        additions: list[str] = []
        for slug in new_slugs:
            if slug not in existing:
                additions.append(f"[[{slug}]]")
                existing.add(slug)
                inserted_count += 1
        if additions:
            section = section.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
        return header + section

    new_body = _SECTION_RE.sub(replacer, body)

    if inserted_count == 0 and not _RELATED_HEADER_RE.search(body):
        # Section was absent - create it
        new_body = body.rstrip("\n") + "\n\n## Related\n" + "\n".join(
            f"[[{s}]]" for s in new_slugs
        ) + "\n"
        inserted_count = len(new_slugs)

    return new_body, inserted_count


def _atomic_write(path: Path, fm: dict, body: str) -> bool:
    """Write frontmatter + body to path atomically. Returns True on success."""
    try:
        from io import StringIO
        from ruamel.yaml import YAML  # type: ignore[import]
        y = YAML()
        y.default_flow_style = False
        y.preserve_quotes    = True
        y.width              = 4096
        buf = StringIO()
        y.dump(fm, buf)
        fm_str = buf.getvalue().rstrip("\n")
    except ImportError:
        import yaml
        fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False).rstrip("\n")

    content = f"---\n{fm_str}\n---\n{body}"
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------------------
# WikilinkResolver - implements IWikilinkResolver
# ---------------------------------------------------------------------------

class WikilinkResolver(IWikilinkResolver):
    """Scores entity pairs and inserts missing [[slug]] cross-references.

    Scoring (per candidate slug against a source file):
      +1 per shared tag (max 3)
      +3 if target slug already wikilinked in source body (outside Related)
      +2 if target slug text appears verbatim in source body
      +1 per shared significant keyword (max 2)
    """

    def __init__(
        self,
        fio: FrontmatterIO,
        min_score: int = MIN_SCORE,
        max_links: int = MAX_LINKS,
    ) -> None:
        self._fio       = fio
        self._min_score = min_score
        self._max_links = max_links
        self._cache: dict[str, tuple[dict, str]] = {}

    def build_slug_index(self, library_dir: Path) -> dict[str, Path]:
        """Return {slug: path} for every .md in library_dir."""
        if not library_dir.is_dir():
            return {}
        return {p.stem: p for p in library_dir.glob("**/*.md")}

    def _load(self, path: Path) -> tuple[dict, str]:
        slug = path.stem
        if slug not in self._cache:
            try:
                fm, body = self._fio.read(path)
                self._cache[slug] = (fm, body)
            except Exception:
                self._cache[slug] = ({}, "")
        return self._cache[slug]

    def _score(
        self,
        source_fm: dict,
        source_body: str,
        target_slug: str,
        target_fm: dict,
        target_body: str,
    ) -> int:
        score = 0

        # Shared tags: +1 each (cap 3)
        src_tags = set(source_fm.get("tags") or [])
        tgt_tags = set(target_fm.get("tags") or [])
        score += min(len(src_tags & tgt_tags), 3)

        # Explicit wikilink in source body above Related: +3
        above = _body_above_related(source_body)
        if has_wikilink(above, target_slug):
            score += 3
        elif target_slug.replace("-", " ") in source_body.lower():
            # Entity name mentioned as prose: +2
            score += 2
        elif target_slug in source_body.lower():
            score += 1

        # Body keyword overlap: +1 each (cap 2)
        src_kw = _extract_keywords(source_body)
        tgt_kw = _extract_keywords(target_body)
        score += min(len(src_kw & tgt_kw), 2)

        # Required-link type boost: +5 if candidate fills a missing required link group
        # (linking-rules.spec.md - per-type enforcement)
        src_linked = (
            slugs_from_relationships(source_fm.get("relationships") or [])
            + extract_wikilinks(source_body)
        )
        score += required_type_boost(
            source_fm.get("type", ""),
            src_linked,
            target_slug,
        )

        return score

    def insert_wikilinks(self, target: Path, slug_index: dict[str, Path]) -> int:
        """Insert missing [[slug]] into ## Related section. Return count inserted."""
        target_fm, target_body = self._load(target)
        target_slug = target.stem

        existing = set(extract_wikilinks(target_body))

        scored: list[tuple[int, str]] = []
        for slug, path in slug_index.items():
            if slug == target_slug or slug in existing:
                continue
            cand_fm, cand_body = self._load(path)
            s = self._score(target_fm, target_body, slug, cand_fm, cand_body)
            if s >= self._min_score:
                scored.append((s, slug))

        scored.sort(key=lambda x: -x[0])
        to_insert = [slug for _, slug in scored[: self._max_links]]

        if not to_insert:
            return 0

        new_body, n = _splice_related(target_body, to_insert)
        if n == 0:
            return 0

        ok = _atomic_write(target, target_fm, new_body)
        if ok:
            self._cache.pop(target_slug, None)
        return n if ok else 0


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _make_store() -> StateStore:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    return StateStore(_STATE_FILE, WIKILINK_STATE_DEFAULT)


def _load_processed(store: StateStore) -> set[str]:
    data = store.load()
    return set(data.keys())


def _mark_processed(store: StateStore, rel: str, links_inserted: int) -> None:
    def updater(data: dict) -> dict:
        data[rel] = {
            "processedAt":   datetime.now(timezone.utc).isoformat(),
            "linksInserted": links_inserted,
        }
        return data
    store.update(updater)


# ---------------------------------------------------------------------------
# main - direct invocation
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Insert [[wikilinks]] into 02-Library/ Related sections")
    parser.add_argument("--min-score", type=int, default=MIN_SCORE,
                        help=f"Minimum pair score to insert a link (default: {MIN_SCORE})")
    parser.add_argument("--max-links", type=int, default=MAX_LINKS,
                        help=f"Max new links inserted per file per run (default: {MAX_LINKS})")
    args, _ = parser.parse_known_args()

    log   = Logger(TASK_ID, SCRIPT_BASENAME, _LOGS_DIR, _MASTER_LOG)
    t0    = log.start()
    store = _make_store()
    store.init_defaults()

    if not _LIBRARY.is_dir():
        log.info("02-Library/ does not exist - nothing to process")
        log.done(t0, key="linked", count=0, failed=0)
        sys.exit(0)

    fio       = FrontmatterIO()
    resolver  = WikilinkResolver(fio, min_score=args.min_score, max_links=args.max_links)
    slug_idx  = resolver.build_slug_index(_LIBRARY)
    processed = _load_processed(store)

    log.info(f"Library: {len(slug_idx)} entities")

    candidates = [
        p for p in sorted(_LIBRARY.glob("**/*.md"))
        if p.relative_to(_PROJECT_ROOT).as_posix() not in processed
    ]

    batch  = candidates[:BATCH_SIZE]
    count  = 0
    failed = 0

    for md_path in batch:
        rel = md_path.relative_to(_PROJECT_ROOT).as_posix()
        try:
            n = resolver.insert_wikilinks(md_path, slug_idx)
            if n:
                log.info(f"Inserted {n} link(s) in {md_path.name}")
            _mark_processed(store, rel, n)
            count += 1
        except Exception as exc:
            log.error(f"Error processing {md_path.name}: {exc}")
            failed += 1

    remaining = len(candidates) - len(batch)
    if remaining:
        log.info(f"{remaining} file(s) queued for next run")

    log.done(t0, key="linked", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "score_entity_pairs",
        "description": (
            "Build a slug index of all approved entities in 02-Library/ "
            "and return the count available for cross-linking."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "insert_wikilinks",
        "description": (
            "Process up to BATCH_SIZE Library entities, inserting missing [[slug]] "
            "cross-references into their ## Related sections (creating the section "
            "if absent). Returns count of files processed and total links inserted."
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

    if name == "score_entity_pairs":
        fio      = FrontmatterIO()
        resolver = WikilinkResolver(fio)
        idx      = resolver.build_slug_index(_LIBRARY)
        return f"Library slug index built: {len(idx)} entities available for cross-linking"

    if name == "insert_wikilinks":
        log      = Logger(TASK_ID, SCRIPT_BASENAME, _LOGS_DIR, _MASTER_LOG)
        store    = _make_store()
        store.init_defaults()
        fio      = FrontmatterIO()
        resolver = WikilinkResolver(fio)
        slug_idx = resolver.build_slug_index(_LIBRARY)
        processed = _load_processed(store)

        count        = 0
        total_links  = 0

        for md_path in sorted(_LIBRARY.glob("**/*.md")):
            if count >= BATCH_SIZE:
                break
            rel = md_path.relative_to(_PROJECT_ROOT).as_posix()
            if rel in processed:
                continue
            try:
                n = resolver.insert_wikilinks(md_path, slug_idx)
                _mark_processed(store, rel, n)
                total_links += n
                count += 1
                if n:
                    log.info(f"Inserted {n} link(s) in {md_path.name}")
            except Exception as exc:
                log.error(f"Error processing {md_path.name}: {exc}")

        return f"Processed {count} file(s); {total_links} link(s) inserted"

    raise ValueError(f"Unknown tool: {name!r}")


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

