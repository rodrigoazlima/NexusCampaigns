"""wikilink.tools.14_wikilink_library

Inserts cross-reference wikilinks into ## Related sections of approved
02-Library/ entities. No LLM. No 00-Inbox or 01-Processing writes.
Batch: 20 files per run.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import FrontmatterIO, extract_wikilinks  # noqa: E402

TASK_ID         = "wikilink-agent"
SCRIPT_BASENAME = "wikilink_library.py"
BATCH_SIZE      = 20

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_LIBRARY     = _VAULT_ROOT / "02-Library"
_AGENT_STATE = _AGENTS_DIR / "wikilink" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_PROCESSED   = _AGENT_STATE / "processed-wikilinks.txt"

_RELATED_SECTION_RE = __import__("re").compile(
    r"(## Related\s*\n)(.*?)(?=\n##|\Z)", __import__("re").DOTALL
)


class _Logger:
    def __init__(self) -> None:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily  = _LOGS_DIR / f"wikilink-library_{today}.log"
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


def _load_processed() -> set[str]:
    if not _PROCESSED.exists():
        return set()
    return {ln.strip() for ln in _PROCESSED.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _mark_processed(rel: str) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    with open(_PROCESSED, "a", encoding="utf-8") as fh:
        fh.write(rel + "\n")


def _collect_library_slugs() -> set[str]:
    if not _LIBRARY.is_dir():
        return set()
    return {p.stem for p in _LIBRARY.glob("**/*.md")}


def _insert_wikilinks(body: str, slugs: set[str]) -> tuple[str, int]:
    """Insert missing [[slug]] into the ## Related section. Returns (new_body, count_added)."""
    import re
    added = 0

    def replacer(m: re.Match) -> str:
        nonlocal added
        header  = m.group(1)
        section = m.group(2)

        existing = set(extract_wikilinks(section))
        new_links: list[str] = []

        for slug in sorted(slugs):
            if slug not in existing and slug.lower() in section.lower():
                new_links.append(f"[[{slug}]]")
                existing.add(slug)
                added += 1

        if new_links:
            section = section.rstrip() + "\n" + "\n".join(new_links) + "\n"

        return header + section

    new_body = _RELATED_SECTION_RE.sub(replacer, body)
    return new_body, added


def _write_with_retry(path: Path, content: str, retries: int = 3) -> bool:
    import time as _time
    for attempt in range(retries):
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return True
        except Exception:
            if attempt < retries - 1:
                _time.sleep(0.3)
    return False


def main() -> None:
    log = _Logger()
    t0  = log.start()
    fio = FrontmatterIO()

    if not _LIBRARY.is_dir():
        log.info("02-Library/ does not exist — nothing to process")
        log.done(t0)
        sys.exit(0)

    all_slugs = _collect_library_slugs()
    processed = _load_processed()

    candidates = [
        p for p in sorted(_LIBRARY.glob("**/*.md"))
        if p.relative_to(_PROJECT_ROOT).as_posix() not in processed
    ]

    batch   = candidates[:BATCH_SIZE]
    count   = 0
    failed  = 0

    for md_path in batch:
        rel = md_path.relative_to(_PROJECT_ROOT).as_posix()
        try:
            fm, body = fio.read(md_path)

            if "## Related" not in body:
                _mark_processed(rel)
                continue

            other_slugs = all_slugs - {md_path.stem}
            new_body, n_added = _insert_wikilinks(body, other_slugs)

            if n_added:
                ok = _write_with_retry(md_path, f"---\n{_dump_fm(fm)}\n---\n{new_body}")
                if ok:
                    log.info(f"Inserted {n_added} wikilinks in {md_path.name}")
                    count += 1
                else:
                    log.error(f"Write failed: {md_path.name}")
                    failed += 1
                    continue
            else:
                count += 1

            _mark_processed(rel)

        except Exception as exc:
            log.error(f"Error processing {md_path.name}: {exc}")
            failed += 1

    remaining = len(candidates) - len(batch)
    if remaining:
        log.info(f"{remaining} file(s) remain for next run")

    log.done(t0, count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


def _dump_fm(fm: dict) -> str:
    try:
        from ruamel.yaml import YAML
        import io as _io
        y = YAML()
        y.default_flow_style = False
        y.width = 4096
        buf = _io.StringIO()
        y.dump(fm, buf)
        return buf.getvalue().rstrip("\n")
    except ImportError:
        import yaml
        return yaml.dump(fm, allow_unicode=True, default_flow_style=False).rstrip("\n")


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
            "cross-references into their ## Related sections. Returns count of files updated."
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
        slugs = _collect_library_slugs()
        return f"Library slug index built: {len(slugs)} entities"

    if name == "insert_wikilinks":
        log = _Logger()
        processed = _load_processed()
        slugs = _collect_library_slugs()
        fio = FrontmatterIO()
        count = 0
        for md_path in sorted(_LIBRARY.glob("**/*.md")):
            rel = md_path.relative_to(_PROJECT_ROOT).as_posix()
            if rel in processed or len([r for r in processed]) == 0:
                pass
            if rel in processed:
                continue
            if count >= BATCH_SIZE:
                break
            try:
                _, body = fio.read(md_path)
                new_body, n = _insert_wikilinks(body, slugs)
                if n > 0:
                    fm, _ = fio.read(md_path)
                    fio.write(md_path, fm, new_body)
                    log.info(f"Inserted {n} link(s) into {md_path.name}")
                _mark_processed(rel)
                count += 1
            except Exception as exc:
                log.error(f"Error processing {md_path.name}: {exc}")
        return f"Processed {count} file(s) with wikilink insertion"

    raise ValueError(f"Unknown tool: {name!r}")
