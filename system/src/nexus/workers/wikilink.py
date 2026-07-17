"""nexus.workers.wikilink - cross-link approved canon (queue consumer, derived pending set).

Scores entity pairs across 02-Library/**/*.md and inserts ## Related
wikilink sections in-place. Replaces nexus.tasks.wikilink_library.

Hard invariants (vault-guard rules):
  - Body-only edits. Frontmatter is read, never written, by this worker.
  - No writes outside 02-Library/. The only worker allowed to write there.
  - status: approved / reviewed: true never touched (human-only fields).
  - Idempotent: re-running on an already-linked file changes nothing.

Pending set is derived: library file mtime vs processedAt in this worker's
own state file (corrupt state ⇒ reprocess all, self-heals).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from nexus.shared import (
    FrontmatterIO,
    StateStore,
    extract_wikilinks,
    has_wikilink,
    slugs_from_relationships,
    required_type_boost,
    WIKILINK_STATE_DEFAULT,
)
from nexus.shared.frontmatter_io import _FENCE_RE
from nexus.shared.interfaces import IWikilinkResolver
from nexus.shared.loaders import _find_project_root
from nexus.workers.base import (
    WorkItem,
    WorkResult,
    adopt_legacy_file,
    make_worker_logger,
    worker_state_dir,
)

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

MIN_SCORE = 1   # minimum pair score to insert a link
MAX_LINKS = 10  # max new links inserted per file per run

_VAULT_ROOT  = _PROJECT_ROOT / ".knowledge-base"
_LIBRARY     = _VAULT_ROOT / "02-Library"

# Legacy homes (nexus.tasks.wikilink_library wrote system/state/wikilink; the
# deployed pipeline wrote agents/wikilink/state) - adopted once, then unused
_LEGACY_STATE_FILES = (
    _PROJECT_ROOT / "system" / "state" / "wikilink" / "wikilink-state.json",
    _PROJECT_ROOT / "agents" / "wikilink" / "state" / "wikilink-state.json",
)

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


def _state_file() -> Path:
    return worker_state_dir("wikilink") / "state.json"


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


def _atomic_write(path: Path, new_body: str) -> bool:
    """Replace the body atomically, keeping the frontmatter block
    byte-for-byte (body-only edits are this worker's hard invariant).
    FrontmatterIO.read's body is exactly the raw text after the fence, so
    fence + new_body round-trips without reserializing YAML."""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return False
    m = _FENCE_RE.match(raw)
    content = (raw[: m.end()] if m else "") + new_body

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

        ok = _atomic_write(target, new_body)
        if ok:
            self._cache.pop(target_slug, None)
        return n if ok else 0


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _make_store() -> StateStore:
    return StateStore(_state_file(), WIKILINK_STATE_DEFAULT)


class WikilinkWorker:
    name = "wikilink"
    kind = "queue"

    def __init__(self, options: dict | None = None) -> None:
        opts = options or {}
        for legacy in _LEGACY_STATE_FILES:
            adopt_legacy_file(legacy, _state_file())
        self._store = _make_store()
        self._store.init_defaults()
        self._fio = FrontmatterIO()
        # Slug index + content cache built lazily, once per instance (= per cycle)
        self._resolver = WikilinkResolver(
            self._fio,
            min_score=int(opts.get("min_score", MIN_SCORE)),
            max_links=int(opts.get("max_links", MAX_LINKS)),
        )
        self._slug_idx: dict[str, Path] | None = None

    def pending(self) -> list[WorkItem]:
        """Library files whose mtime > processedAt (corrupt state ⇒ all)."""
        if not _LIBRARY.is_dir():
            return []
        try:
            state = self._store.load()
        except Exception:
            state = {}
        items: list[WorkItem] = []
        for f in sorted(_LIBRARY.glob("**/*.md")):
            rel = f.relative_to(_PROJECT_ROOT).as_posix()
            entry = state.get(rel)
            if entry is not None:
                try:
                    processed_ts = datetime.fromisoformat(entry["processedAt"]).timestamp()
                    if f.stat().st_mtime <= processed_ts:
                        continue
                except Exception:
                    pass  # corrupt entry → reprocess
            items.append(WorkItem(rel, {}))
        return items

    def handle(self, item: WorkItem) -> WorkResult:
        log = make_worker_logger(self.name)
        md_path = _PROJECT_ROOT / item.key
        if not md_path.exists():
            return WorkResult("skip", "file gone")

        if self._slug_idx is None:
            self._slug_idx = self._resolver.build_slug_index(_LIBRARY)
            log.info(f"Library: {len(self._slug_idx)} entities")

        try:
            n = self._resolver.insert_wikilinks(md_path, self._slug_idx)
        except Exception as exc:
            self._mark(item.key, 0, error=str(exc))
            log.error(f"Error processing {md_path.name}: {exc}")
            return WorkResult("error", f"{md_path.name}: {exc}")

        self._mark(item.key, n)
        if n:
            log.info(f"Inserted {n} link(s) in {md_path.name}")
        return WorkResult("done", f"{n} link(s) inserted")

    def _mark(self, rel: str, links_inserted: int, error: str | None = None) -> None:
        def updater(data: dict) -> dict:
            entry = {
                "processedAt":   datetime.now(timezone.utc).isoformat(),
                "linksInserted": links_inserted,
            }
            if error:
                entry["error"] = error
            data[rel] = entry
            return data
        self._store.update(updater)


def create(options: dict | None = None) -> WikilinkWorker:
    return WikilinkWorker(options)


if __name__ == "__main__":
    worker = create()
    for _item in worker.pending():
        _res = worker.handle(_item)
        print(f"{_res.status} {_item.key}: {_res.detail}")
