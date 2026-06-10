"""classification.tools.04_enrich_tags

Enriches .md files in 00-Inbox/ and 01-Processing/ with DM-domain tags
and entity type inference via LocalRouter LLM.
Only processes files with <= 5 existing tags or missing type field.
No LLM → skip gracefully.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

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
    TagEnrichmentOutput,
)
from shared.config import LLMEndpointConfig  # noqa: E402

TASK_ID         = "classification-agent"
SCRIPT_BASENAME = "enrich_tags.py"

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_INBOX       = _VAULT_ROOT / "00-Inbox"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_LIBRARY     = _VAULT_ROOT / "02-Library"
_AGENT_STATE = _AGENTS_DIR / "classification" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_BAD_DOCS    = _AGENT_STATE / "bad-docs.txt"
_PROMPT_FILE = _AGENTS_DIR / "classification" / "prompts" / "enrich-tags.txt"

_ALLOWED_TAGS = frozenset({
    "npc", "creature", "monster", "location", "dungeon", "city", "village",
    "faction", "quest", "encounter", "item", "artifact", "lore", "religion",
    "event", "organization", "timeline", "undead", "dark", "fire", "light",
    "none", "portrait", "battlemap", "scene", "token", "images", "pathfinder2e",
})
_ALLOWED_TYPES = frozenset({
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


class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"enrich-tags_{today}.log"
        self._master = _MASTER_LOG

    def _write(self, level: str, msg: str) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{TASK_ID}] {level}: {msg}"
        print(line, flush=True)
        self._master.parent.mkdir(parents=True, exist_ok=True)
        for p in (self._master, self._daily):
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, m: str)    -> None: self._write("INFO",  m)
    def warning(self, m: str) -> None: self._write("WARN",  m)
    def error(self, m: str)   -> None: self._write("ERROR", m)

    def start(self) -> float:
        self._write("INFO", "--- START ---")
        return time.monotonic()

    def done(self, t0: float, count: int = 0, failed: int = 0) -> None:
        elapsed = round(time.monotonic() - t0, 2)
        self._write("INFO", f"--- DONE --- processed={count} failed={failed} elapsed={elapsed}s")


def _load_bad_docs() -> set[str]:
    if not _BAD_DOCS.exists():
        return set()
    return {ln.strip() for ln in _BAD_DOCS.read_text(encoding="utf-8").splitlines() if ln.strip()}


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


def _write_with_retry(path: Path, fm: dict, body: str, fio: FrontmatterIO, retries: int = 5) -> bool:
    for attempt in range(retries):
        try:
            fio.write(path, fm, body)
            return True
        except Exception:
            if attempt < retries - 1:
                time.sleep(0.3)
    return False


def main() -> None:
    log = _Logger()
    t0  = log.start()
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("LocalRouter (localhost:8080) offline — skipping batch")
        log.done(t0)
        sys.exit(0)

    bad_docs    = _load_bad_docs()
    lib_slugs   = _library_slugs()
    fio         = FrontmatterIO()
    prompt_tpl  = (
        _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists()
        else "Tag this note. Return JSON: {\"tags\": [], \"type\": null}"
    )
    count  = 0
    failed = 0

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

        prompt = (
            prompt_tpl
            .replace("{title}", title)
            .replace("{current_tags}", ", ".join(existing_tags) if existing_tags else "none")
            .replace("{content}", excerpt)
        )

        try:
            import json as _json
            raw = client.chat([{"role": "user", "content": prompt}], max_tokens=80)
            result = _json.loads(raw)
            enrichment = TagEnrichmentOutput.model_validate(result)
        except LLMOfflineError:
            log.warning("LLM offline — aborting batch")
            break
        except (LLMResponseError, Exception) as exc:
            log.error(f"LLM error for {md_path.name}: {exc}")
            _append_bad(rel)
            failed += 1
            time.sleep(0.3)
            continue

        changed = False

        if needs_tags and enrichment.tags:
            valid_new = [t for t in enrichment.tags if t in _ALLOWED_TAGS and t not in existing_tags]
            if valid_new:
                fm["tags"] = list(existing_tags) + valid_new
                changed = True

        if needs_type and enrichment.type and enrichment.type in _ALLOWED_TYPES:
            fm["type"] = enrichment.type
            changed = True

        if fm.get("id") and fm["id"].lower() in lib_slugs:
            fm["duplicate_of"] = fm["id"]
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

    log.done(t0, count=count, failed=failed)
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
        "name": "enrich_tags",
        "description": (
            "Process up to BATCH_SIZE notes in 00-Inbox/ and 01-Processing/ that have "
            "5 or fewer tags or a missing type field. Calls local LLM to suggest tags and type. "
            "Returns count of enriched files."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "flag_duplicates",
        "description": (
            "Check processed files for IDs that match existing 02-Library/ slugs "
            "and mark them with duplicate_of in frontmatter."
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
        # Delegate to main() logic via a fresh run
        import io
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue() or "Enrichment run complete"

    if name == "flag_duplicates":
        lib_slugs = _library_slugs()
        fio = FrontmatterIO()
        flagged = 0
        for scope in (_INBOX, _PROCESSING):
            for md_path in sorted(scope.glob("**/*.md")):
                try:
                    fm, body = fio.read(md_path)
                    if fm.get("id") and fm["id"].lower() in lib_slugs:
                        fm["duplicate_of"] = fm["id"]
                        fio.write(md_path, fm, body)
                        flagged += 1
                except Exception:
                    continue
        return f"Flagged {flagged} potential duplicate(s)"

    raise ValueError(f"Unknown tool: {name!r}")
