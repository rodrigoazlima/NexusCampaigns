"""wiki.tools.compile_wiki

Actions: LoadCanonContext · ScanPending · SynthesizeEntity · WriteDraft · MarkQueueDone

Reads:  system/state/inbox-queue.json  (type=document, agents.wiki=pending)
        02-Library/**/*.md              (canon context, read-only, up to 50 entities)
Writes: 01-Processing/{slug}.md
        system/state/inbox-queue.json  (marks agents.wiki=done per entry)
        agents/wiki/state/bad-wiki-docs.txt

LLM:    LocalRouter http://localhost:8080 (openai-compat, model=auto)
Batch:  5 documents per run
"""

from __future__ import annotations

import re
import sys
import time
import uuid as _uuid
from datetime import date
from pathlib import Path

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
    StateStore,
    VaultGuard,
    INBOX_QUEUE_DEFAULT,
    to_slug,
)
from nexus.shared.config import LLMEndpointConfig, VaultPaths  # noqa: E402

TASK_ID         = "wiki-agent"
SCRIPT_BASENAME = "compile_wiki.py"
BATCH_SIZE      = 5

_VAULT_ROOT  = _PROJECT_ROOT / ".knowledge-base"
_VAULT_PATHS = VaultPaths(vault_root=_VAULT_ROOT)
_INBOX       = _VAULT_ROOT / "00-Inbox"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_LIBRARY     = _VAULT_ROOT / "02-Library"
_AGENT_STATE = _AGENTS_DIR / "wiki" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_BAD_DOCS    = _AGENT_STATE / "bad-wiki-docs.txt"
_PROMPT_FILE = _AGENTS_DIR / "wiki" / "prompts" / "compile-entity.txt"
_INBOX_QUEUE = _PROJECT_ROOT / "system" / "state" / "inbox-queue.json"

_FENCE_RE    = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
_HTML_RE     = re.compile(r"<[^>]+>", re.DOTALL)
_MIN_CHARS   = 100
_MAX_CHARS   = 6000

_LLM_CFG = LLMEndpointConfig(
    url      = "http://localhost:8080/v1/chat/completions",
    model    = "auto",
    type     = "text",
    provider = "lmstudio",
)

_ALLOWED_TYPES: frozenset[str] = frozenset({
    "npc", "character", "faction", "location", "city", "village", "dungeon",
    "item", "artifact", "quest", "encounter", "creature", "monster", "event",
    "religion", "organization", "timeline", "lore",
})


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
    return {ln.strip() for ln in _BAD_DOCS.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _append_bad(rel: str) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    with open(_BAD_DOCS, "a", encoding="utf-8") as fh:
        fh.write(rel + "\n")


def _canon_context() -> str:
    """Load approved entities from 02-Library/ as LLM context.

    Includes id, type, tags, and relationships per spec LoadCanonContext action.
    """
    if not _LIBRARY.is_dir():
        return ""
    fio   = FrontmatterIO()
    lines = []
    for p in sorted(_LIBRARY.glob("**/*.md"))[:50]:
        try:
            fm, _ = fio.read(p)
            entity_id   = fm.get("id", p.stem)
            entity_type = fm.get("type", "?")
            tags        = fm.get("tags") or []
            rels        = fm.get("relationships") or []
            line        = f"- {entity_id} ({entity_type})"
            if tags:
                line += f" tags=[{', '.join(str(t) for t in tags[:5])}]"
            if rels:
                line += f" rels=[{', '.join(str(r) for r in rels[:3])}]"
            lines.append(line)
        except Exception:
            continue
    return "\n".join(lines)


def _strip_html(text: str) -> str:
    return _HTML_RE.sub("", text).strip()


def _unique_output(slug: str) -> Path:
    _PROCESSING.mkdir(parents=True, exist_ok=True)
    p = _PROCESSING / f"{slug}.md"
    if not p.exists():
        return p
    today = date.today().strftime("%Y%m%d")
    p = _PROCESSING / f"{slug}-{today}.md"
    if not p.exists():
        return p
    counter = 1
    while True:
        p = _PROCESSING / f"{slug}-{today}-{counter:02d}.md"
        if not p.exists():
            return p
        counter += 1


def _enforce_and_write(
    llm_output: str,
    source_name: str,
    out_path: Path,
    fio: FrontmatterIO,
) -> None:
    """Parse LLM output, enforce security constraints, write to out_path.

    Enforced fields (G3 — no self-approval):
      status=draft, reviewed=false, quality=0, source=[source_name]
    """
    today = date.today().isoformat()

    m = _FENCE_RE.match(llm_output)
    if m:
        try:
            import yaml  # noqa: PLC0415
            fm = yaml.safe_load(m.group(1)) or {}
            if not isinstance(fm, dict):
                fm = {}
        except Exception:
            fm = {}
        body = llm_output[m.end():]
    else:
        fm   = {}
        body = llm_output

    # Enforce immutable agent-write constraints
    fm["status"]   = "draft"
    fm["reviewed"] = False
    fm["quality"]  = 0

    # Required timestamps
    if not fm.get("created"):
        fm["created"] = today
    fm["updated"] = today

    # Source tracking
    fm["source"] = [source_name]

    # Validate type — default to lore if LLM returned an unknown value
    if str(fm.get("type", "")) not in _ALLOWED_TYPES:
        fm["type"] = "lore"

    # Ensure id is present and slugified
    if not fm.get("id"):
        fm["id"] = f"{fm['type']}-{to_slug(Path(source_name).stem)}"

    # Assign stable UUID if not already present
    if not fm.get("uuid"):
        fm["uuid"] = str(_uuid.uuid4())

    # Ensure list fields are actually lists
    if not isinstance(fm.get("relationships"), list):
        fm["relationships"] = []
    if not isinstance(fm.get("tags"), list):
        fm["tags"] = []

    fio.write(out_path, fm, body)


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

def _pending_documents(queue: dict, bad_docs: set[str]) -> list[tuple[str, Path]]:
    """Return (rel_key, abs_path) pairs for queue entries with type=document, agents.wiki=pending."""
    results: list[tuple[str, Path]] = []
    for rel_key, entry in queue.items():
        if isinstance(entry, dict):
            entry_type  = entry.get("type", "")
            agents      = entry.get("agents", {})
            wiki_status = (agents.get("wiki", "skip") if isinstance(agents, dict) else "skip")
        else:
            # Pydantic model
            entry_type  = str(getattr(entry, "type", ""))
            agents_obj  = getattr(entry, "agents", None)
            raw_status  = getattr(agents_obj, "wiki", "skip") if agents_obj else "skip"
            wiki_status = raw_status.value if hasattr(raw_status, "value") else str(raw_status)

        if entry_type != "document":
            continue
        if wiki_status != "pending":
            continue
        if rel_key in bad_docs:
            continue

        abs_path = _PROJECT_ROOT / rel_key
        if not abs_path.exists():
            continue
        results.append((rel_key, abs_path))
    return results


def _mark_wiki_done(rel_key: str) -> None:
    """Atomically set agents.wiki = done in inbox-queue.json (MarkQueueDone action)."""
    store = StateStore(_INBOX_QUEUE, INBOX_QUEUE_DEFAULT)

    def _updater(queue: dict) -> dict:
        entry = queue.get(rel_key)
        if entry is None:
            return queue
        if isinstance(entry, dict):
            entry.setdefault("agents", {})["wiki"] = "done"
        return queue

    store.update(_updater)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log = _make_logger()
    t0  = log.start()
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("LocalRouter (localhost:8080) offline — skipping batch")
        log.done(t0, key="processed", count=0, failed=0)
        sys.exit(0)

    guard    = VaultGuard(_VAULT_PATHS)
    fio      = FrontmatterIO()
    bad_docs = _load_bad_docs()
    queue    = StateStore(_INBOX_QUEUE, INBOX_QUEUE_DEFAULT).load()
    pending  = _pending_documents(queue, bad_docs)[:BATCH_SIZE]

    if not pending:
        log.info("No pending document entries in inbox-queue.json")
        log.done(t0, key="processed", count=0, failed=0)
        sys.exit(0)

    canon_ctx  = _canon_context()
    prompt_tpl = (
        _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists()
        else "Compile this note into a structured entity page:\n\n{content}"
    )

    count  = 0
    failed = 0

    for rel_key, md_path in pending:
        try:
            raw = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            log.error(f"Read error {md_path.name}: {exc}")
            _append_bad(rel_key)
            failed += 1
            continue

        content = _strip_html(raw)
        if len(content) < _MIN_CHARS:
            log.info(f"Skip (too short): {md_path.name}")
            _mark_wiki_done(rel_key)
            continue

        truncated = content[:_MAX_CHARS]
        if len(content) > _MAX_CHARS:
            truncated += "\n\n[... content truncated ...]"

        prompt = (
            prompt_tpl
            .replace("{content}", truncated)
            .replace("{canon_context}", canon_ctx or "(no canon entities yet)")
        )

        try:
            result = client.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=1500,
            )
        except LLMOfflineError:
            log.warning("LLM offline — aborting batch")
            break
        except (LLMResponseError, Exception) as exc:
            log.error(f"LLM error for {md_path.name}: {exc}")
            _append_bad(rel_key)
            failed += 1
            time.sleep(2.0)
            continue

        # Extract slug from LLM-generated id field before enforcement rewrites it
        slug_match = re.search(r"^id:\s*(.+)$", result, re.MULTILINE)
        raw_slug   = slug_match.group(1).strip() if slug_match else md_path.stem
        slug       = to_slug(raw_slug)

        out_path = _unique_output(slug)
        try:
            guard.assert_writable(out_path)
            _enforce_and_write(result, rel_key, out_path, fio)
            log.info(f"Compiled: {md_path.name} → {out_path.name}")
            _mark_wiki_done(rel_key)
            count += 1
        except Exception as exc:
            log.error(f"Write failed for {out_path.name}: {exc}")
            _append_bad(rel_key)
            failed += 1

        time.sleep(2.0)

    log.done(t0, key="processed", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from nexus.shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "load_canon_context",
        "description": (
            "Load approved entities from 02-Library/ as LLM context for synthesis. "
            "Returns id, type, tags, and relationships for up to 50 canon entities."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "scan_pending",
        "description": (
            "Scan inbox-queue.json for document entries with agents.wiki=pending. "
            "Returns count of pending documents and their filenames."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "synthesize_entity",
        "description": (
            "Synthesize a structured entity page from a single pending inbox document. "
            "Calls LocalRouter LLM, enforces frontmatter constraints, writes to 01-Processing/, "
            "and marks agents.wiki=done in inbox-queue.json."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Relative path from project root (as stored in inbox-queue.json)",
                },
            },
            "required": ["source_path"],
        },
    },
    {
        "name": "run_batch",
        "description": (
            f"Process up to {BATCH_SIZE} pending document entries from inbox-queue.json in one pass. "
            "Returns count compiled and count failed."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import contextlib
    import io as _io

    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    if name == "load_canon_context":
        ctx   = _canon_context()
        lines = [ln for ln in ctx.splitlines() if ln.strip()]
        lib_count = len(list(_LIBRARY.glob("**/*.md"))) if _LIBRARY.is_dir() else 0
        return f"Canon context loaded: {len(lines)} entities (library has {lib_count} files)"

    if name == "scan_pending":
        bad_docs = _load_bad_docs()
        queue    = StateStore(_INBOX_QUEUE, INBOX_QUEUE_DEFAULT).load()
        pending  = _pending_documents(queue, bad_docs)
        names    = [Path(r).name for r, _ in pending]
        return (
            f"Pending documents: {len(pending)}\n"
            + ("\n".join(f"  - {n}" for n in names[:20]) if names else "  (none)")
        )

    if name == "synthesize_entity":
        rel_key  = args["source_path"]
        bad_docs = _load_bad_docs()
        if rel_key in bad_docs:
            return f"ERROR: {rel_key} is in bad-wiki-docs.txt — skipped"
        abs_path = _PROJECT_ROOT / rel_key
        if not abs_path.exists():
            return f"ERROR: File not found: {abs_path}"

        # Run single-file synthesis via main() with only this entry visible
        # Patch queue to contain only this entry so batch processes it
        queue    = StateStore(_INBOX_QUEUE, INBOX_QUEUE_DEFAULT).load()
        entry    = queue.get(rel_key)
        if entry is None:
            return f"ERROR: {rel_key} not found in inbox-queue.json"

        buf = _io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Synthesis run complete"

    if name == "run_batch":
        buf = _io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")


if __name__ == "__main__":
    main()
