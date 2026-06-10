"""wiki.tools.03_compile_wiki

Compiles 00-Inbox/*.md notes into structured 01-Processing/ entity drafts via LLM.
No LLM → skip gracefully. Batch: per run, up to files not yet processed.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

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
)
from shared.config import LLMEndpointConfig  # noqa: E402

TASK_ID         = "wiki-agent"
SCRIPT_BASENAME = "compile_wiki.py"

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_INBOX       = _VAULT_ROOT / "00-Inbox"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_LIBRARY     = _VAULT_ROOT / "02-Library"
_AGENT_STATE = _AGENTS_DIR / "wiki" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_PROCESSED   = _AGENT_STATE / "processed.txt"
_BAD_DOCS    = _AGENT_STATE / "bad-wiki-docs.txt"
_PROMPT_FILE = _AGENTS_DIR / "wiki" / "prompts" / "compile-entity.txt"

_HTML_RE     = re.compile(r"<[^>]+>", re.DOTALL)
_MIN_CHARS   = 100
_MAX_CHARS   = 6000

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
        self._daily  = _LOGS_DIR / f"compile-wiki_{today}.log"
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


def _load_skip_list(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _append_skip(path: Path, rel: str) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(rel + "\n")


def _canon_context() -> str:
    if not _LIBRARY.is_dir():
        return ""
    fio   = FrontmatterIO()
    lines = []
    for p in sorted(_LIBRARY.glob("**/*.md"))[:50]:
        try:
            fm, _ = fio.read(p)
            lines.append(f"- {fm.get('id', p.stem)} ({fm.get('type', '?')})")
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


def main() -> None:
    log = _Logger()
    t0  = log.start()
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("LocalRouter (localhost:8080) offline — skipping batch")
        log.done(t0)
        sys.exit(0)

    processed = _load_skip_list(_PROCESSED)
    bad_docs  = _load_skip_list(_BAD_DOCS)
    canon_ctx = _canon_context()
    prompt_tpl = (
        _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists()
        else "Compile this note into a structured entity page:\n\n{content}"
    )

    candidates = [
        p for p in sorted(_INBOX.rglob("*.md"))
        if ".git" not in p.parts
        if ".agents" not in p.parts
        if p.relative_to(_PROJECT_ROOT).as_posix() not in processed
        if p.relative_to(_PROJECT_ROOT).as_posix() not in bad_docs
    ]

    count  = 0
    failed = 0

    for md_path in candidates:
        rel = md_path.relative_to(_PROJECT_ROOT).as_posix()
        try:
            raw = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            log.error(f"Read error {md_path.name}: {exc}")
            _append_skip(_BAD_DOCS, rel)
            failed += 1
            continue

        content = _strip_html(raw)
        if len(content) < _MIN_CHARS:
            log.info(f"Skip (too short): {md_path.name}")
            _append_skip(_PROCESSED, rel)
            continue

        truncated = content[:_MAX_CHARS]
        if len(content) > _MAX_CHARS:
            truncated += "\n\n[... content truncated ...]"

        prompt = prompt_tpl.replace("{content}", truncated)

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
            _append_skip(_BAD_DOCS, rel)
            failed += 1
            time.sleep(2.0)
            continue

        # Extract slug from result if it contains frontmatter id
        slug_match = re.search(r"^id:\s*(.+)$", result, re.MULTILINE)
        slug = slug_match.group(1).strip() if slug_match else md_path.stem

        from shared.slug_utils import to_slug as _to_slug
        slug = _to_slug(slug)

        out_path = _unique_output(slug)
        try:
            out_path.write_text(result, encoding="utf-8")
            log.info(f"Compiled: {md_path.name} → {out_path.name}")
            _append_skip(_PROCESSED, rel)
            count += 1
        except Exception as exc:
            log.error(f"Write failed for {out_path.name}: {exc}")
            _append_skip(_BAD_DOCS, rel)
            failed += 1

        time.sleep(2.0)

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
        "name": "load_canon_context",
        "description": "Load approved entities from 02-Library/ as context for synthesis. Returns a summary of canon entities available.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "synthesize_entity",
        "description": "Synthesize a structured entity page from a raw 00-Inbox markdown note using the local LLM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Absolute path to the inbox .md source file"},
            },
            "required": ["source_path"],
        },
    },
    {
        "name": "run_batch",
        "description": "Process up to BATCH_SIZE unprocessed inbox notes in one pass. Returns count compiled.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import io, contextlib
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _Logger()

    if name == "load_canon_context":
        ctx = _canon_context()
        lines = [l for l in ctx.splitlines() if l.strip()]
        return f"Canon context loaded: {len(lines)} lines covering {_LIBRARY.is_dir() and len(list(_LIBRARY.glob('**/*.md'))) or 0} entities"

    if name == "synthesize_entity":
        src = Path(args["source_path"])
        if not src.exists():
            return f"ERROR: File not found: {src}"
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Synthesis run complete"

    if name == "run_batch":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")
