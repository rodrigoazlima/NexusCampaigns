"""ingestion.tools.ingestion_agent

Ingestion Agent — first stage of the vault pipeline.
  - Strips emoji from filenames in 00-Inbox/ (idempotent)
  - Converts .docx files vault-wide to GFM Markdown via Pandoc
  - Registers new Inbox files into .system/state/inbox-queue.json

No LLM calls. No 02-Library writes. No 00-Inbox deletes.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# .agents/ must be on sys.path so `import shared` resolves
_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import (  # noqa: E402
    AgentSlots,
    AgentSlotStatus,
    BaseAgent,
    InboxQueue,
    InboxQueueEntry,
)
from shared.logger import Logger  # noqa: E402
from shared.loaders import load_vault_config  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_ID         = "ingestion-agent"
SCRIPT_BASENAME = "ingestion_agent"
BATCH_SIZE      = 10
DONE_KEY        = "processed"

IMAGE_EXTS    = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"})
DOCUMENT_EXTS = frozenset({".docx", ".doc", ".pdf", ".md", ".txt", ".odt"})

_VAULT_ROOT   = _PROJECT_ROOT / "knowledge-base"
_INBOX        = _VAULT_ROOT / "00-Inbox"
_SHARED_STATE = _PROJECT_ROOT / ".system" / "state"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"

_AGENT_STATE    = _AGENTS_DIR / "ingestion" / "state"
_LOGS_DIR       = _AGENT_STATE / "logs"
_PROCESSED_DOCX = _AGENT_STATE / "processed-docx.txt"

# Unicode ranges covering common emoji blocks
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F300-\U0001F5FF"   # symbols & pictographs
    "\U0001F680-\U0001F6FF"   # transport & map
    "\U0001F700-\U0001F77F"   # alchemical symbols
    "\U0001F780-\U0001F7FF"   # geometric shapes extended
    "\U0001F800-\U0001F8FF"   # supplemental arrows-C
    "\U0001F900-\U0001F9FF"   # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"   # chess symbols
    "\U0001FA70-\U0001FAFF"   # symbols and pictographs extended-A
    "\U00002700-\U000027BF"   # dingbats
    "\U000024C2-\U0001F251"   # enclosed alphanumerics
    "\U0000200D"               # zero-width joiner
    "\U000020E3"               # combining enclosing keycap
    "\U0000FE0F"               # variation selector-16
    "]+",
    flags=re.UNICODE,
)


# ---------------------------------------------------------------------------
# Logger factory — used by call_tool() agentic dispatch (no agent instance)
# ---------------------------------------------------------------------------

def _make_logger() -> Logger:
    """Construct a shared Logger from module-level path constants."""
    return Logger(
        task_id         = TASK_ID,
        script_basename = SCRIPT_BASENAME,
        logs_dir        = _LOGS_DIR,
        master_log      = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log",
    )


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------

def _load_queue() -> InboxQueue:
    if not _QUEUE_FILE.exists():
        return {}
    raw: dict = json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    return {k: InboxQueueEntry.model_validate(v) for k, v in raw.items()}


def _save_queue(queue: InboxQueue) -> None:
    _SHARED_STATE.mkdir(parents=True, exist_ok=True)
    tmp     = _QUEUE_FILE.with_suffix(".tmp")
    payload = {k: v.model_dump(mode="json") for k, v in queue.items()}
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(_QUEUE_FILE)


# ---------------------------------------------------------------------------
# Processed-DOCX state
# ---------------------------------------------------------------------------

def _load_processed_docx() -> set[str]:
    if not _PROCESSED_DOCX.exists():
        return set()
    return {
        ln.strip()
        for ln in _PROCESSED_DOCX.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }


def _mark_docx_processed(path: Path) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    rel = path.relative_to(_PROJECT_ROOT).as_posix()
    with open(_PROCESSED_DOCX, "a", encoding="utf-8") as fh:
        fh.write(rel + "\n")


# ---------------------------------------------------------------------------
# Emoji stripping
# ---------------------------------------------------------------------------

def _strip_emoji(text: str) -> str:
    """Remove emoji and collapse surrounding whitespace/separators."""
    cleaned = _EMOJI_RE.sub("", text)
    cleaned = re.sub(r"[\s_\-]{2,}", "-", cleaned).strip(" _-")
    return cleaned or text  # never return empty


def strip_emoji_filenames(inbox: Path, log: Logger) -> int:
    """Rename files in inbox/ that contain emoji. Idempotent. Returns count renamed."""
    renamed = 0
    for path in sorted(inbox.rglob("*")):
        if not path.is_file():
            continue
        if not _EMOJI_RE.search(path.stem):
            continue

        clean_stem = _strip_emoji(path.stem)
        candidate  = path.with_name(clean_stem + path.suffix)
        if candidate == path:
            continue

        if candidate.exists():
            ts        = datetime.now().strftime("%Y%m%d%H%M%S")
            candidate = path.with_name(f"{clean_stem}-{ts}{path.suffix}")

        path.rename(candidate)
        log.info(f"Emoji strip: {path.name!r} → {candidate.name!r}")
        renamed += 1

    return renamed


# ---------------------------------------------------------------------------
# Pandoc / DOCX conversion
# ---------------------------------------------------------------------------

def _ensure_pandoc(log: Logger) -> bool:
    if shutil.which("pandoc"):
        return True
    log.warning("pandoc not found — attempting: winget install JohnMacFarlane.Pandoc")
    try:
        result = subprocess.run(
            ["winget", "install", "--id", "JohnMacFarlane.Pandoc", "-e", "--silent"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and shutil.which("pandoc"):
            log.info("pandoc installed via winget")
            return True
        log.error(f"winget install failed (rc={result.returncode}): {result.stderr.strip()[:200]}")
    except Exception as exc:
        log.error(f"winget error: {exc}")
    return False


def _to_slug(stem: str) -> str:
    s = stem.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "document"


def _convert_docx(docx_path: Path, log: Logger) -> Optional[Path]:
    """Convert one DOCX → GFM Markdown. Images → 00-Inbox/images/{slug}/. Returns .md or None."""
    slug       = _to_slug(docx_path.stem)
    images_dir = _INBOX / "images" / slug
    images_dir.mkdir(parents=True, exist_ok=True)

    out_md = _INBOX / "docs" / f"{slug}.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "pandoc", str(docx_path),
        "-f", "docx",
        "-t", "gfm",
        "--extract-media", str(images_dir),
        "-o", str(out_md),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log.error(f"pandoc failed ({docx_path.name}): {result.stderr.strip()[:300]}")
            return None
    except Exception as exc:
        log.error(f"pandoc subprocess error ({docx_path.name}): {exc}")
        return None

    _flatten_media(images_dir, out_md, log)
    log.info(f"Converted DOCX: {docx_path.name} → {out_md.name}")
    return out_md


def _flatten_media(images_dir: Path, md_path: Path, log: Logger) -> None:
    """Move pandoc's media/ subdir files up into images_dir, fix md image refs."""
    media_sub = images_dir / "media"
    if not media_sub.exists():
        return

    moved = 0
    for img in list(media_sub.iterdir()):
        if img.is_file():
            dest = images_dir / img.name
            if dest.exists():
                ts   = datetime.now().strftime("%Y%m%d%H%M%S")
                dest = images_dir / f"{img.stem}-{ts}{img.suffix}"
            img.rename(dest)
            moved += 1

    try:
        media_sub.rmdir()
    except OSError:
        pass  # non-empty after move (subdirs) — leave it

    if moved and md_path.exists():
        _fix_md_image_refs(md_path, images_dir)
        log.info(f"Flattened {moved} media file(s) → {images_dir.name}/")


def _fix_md_image_refs(md_path: Path, images_dir: Path) -> None:
    """Rewrite absolute pandoc media paths to vault-relative paths in md."""
    try:
        content = md_path.read_text(encoding="utf-8")

        abs_media = (images_dir / "media").as_posix()
        rel_media = images_dir.relative_to(_PROJECT_ROOT).as_posix()

        content = content.replace(abs_media + "/", rel_media + "/")
        content = content.replace(str(images_dir / "media").replace("/", "\\") + "\\", rel_media + "/")
        content = re.sub(
            r"!\[([^\]]*)\]\(media/([^)]+)\)",
            lambda m: f"![{m.group(1)}]({rel_media}/{m.group(2)})",
            content,
        )

        md_path.write_text(content, encoding="utf-8")
    except Exception:
        pass  # non-fatal — images still exist, paths just need manual fix


def process_docx_files(log: Logger) -> tuple[int, int]:
    """Discover + convert unprocessed .docx files vault-wide (max BATCH_SIZE)."""
    if not _ensure_pandoc(log):
        log.warning("DOCX conversion skipped — pandoc unavailable")
        return 0, 0

    processed = _load_processed_docx()
    all_docx  = [
        p for p in _VAULT_ROOT.rglob("*.docx")
        if ".git"    not in p.parts
        if ".agents" not in p.parts
        if p.relative_to(_PROJECT_ROOT).as_posix() not in processed
    ]

    batch = all_docx[:BATCH_SIZE]
    if not batch:
        return 0, 0

    log.info(f"DOCX batch: {len(batch)} of {len(all_docx)} unprocessed file(s)")
    count, failed = 0, 0
    for docx_path in batch:
        out = _convert_docx(docx_path, log)
        if out:
            _mark_docx_processed(docx_path)
            count += 1
        else:
            failed += 1

    return count, failed


# ---------------------------------------------------------------------------
# Queue registration
# ---------------------------------------------------------------------------

def _file_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in DOCUMENT_EXTS:
        return "document"
    return "other"


def _make_slots(file_type: str) -> AgentSlots:
    p = AgentSlotStatus.pending
    s = AgentSlotStatus.skip
    if file_type == "image":
        return AgentSlots(vision=p, lore=p, classification=p, wiki=s)
    if file_type == "document":
        return AgentSlots(vision=s, lore=s, classification=p, wiki=p)
    return AgentSlots(vision=s, lore=s, classification=s, wiki=s)


def register_new_files(log: Logger) -> tuple[int, int]:
    """Scan 00-Inbox/ recursively; add files absent from queue. Returns (added, 0)."""
    queue = _load_queue()
    added = 0

    for path in sorted(_INBOX.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(_PROJECT_ROOT).as_posix()
        if rel in queue:
            continue

        ft            = _file_type(path)
        queue[rel]    = InboxQueueEntry(
            ingestedAt=datetime.now(timezone.utc),
            type=ft,
            agents=_make_slots(ft),
        )
        log.info(f"Queued [{ft}]: {rel}")
        added += 1

    if added:
        _save_queue(queue)
        log.info(f"Queue saved — {added} new entry/entries (total: {len(queue)})")

    return added, 0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IngestionAgent(BaseAgent):
    TASK_ID         = TASK_ID
    SCRIPT_BASENAME = SCRIPT_BASENAME
    BATCH_SIZE      = BATCH_SIZE
    DONE_KEY        = DONE_KEY

    def __init__(self) -> None:
        cfg = load_vault_config(_PROJECT_ROOT)
        super().__init__(cfg=cfg)

    def bootstrap(self) -> None:
        """Ensure required state dirs and queue file exist. Idempotent."""
        _AGENT_STATE.mkdir(parents=True, exist_ok=True)
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _SHARED_STATE.mkdir(parents=True, exist_ok=True)
        (_INBOX / "docs").mkdir(parents=True, exist_ok=True)
        (_INBOX / "images").mkdir(parents=True, exist_ok=True)
        if not _QUEUE_FILE.exists():
            _save_queue({})

    def run_batch(self) -> tuple[int, int]:
        # self._logger set by BaseAgent.execute() before run_batch() is called
        log = self._logger
        total_count, total_failed = 0, 0

        renamed = strip_emoji_filenames(_INBOX, log)
        total_count += renamed

        docx_count, docx_failed = process_docx_files(log)
        total_count  += docx_count
        total_failed += docx_failed

        added, _ = register_new_files(log)
        total_count += added

        return total_count, total_failed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    agent = IngestionAgent()
    sys.exit(agent.execute())


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface (claude-api tool-use dispatch)
# ---------------------------------------------------------------------------

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "clean_filenames",
        "description": "Strip emoji and non-ASCII characters from all filenames in 00-Inbox/. Idempotent.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "convert_docx",
        "description": "Convert all unprocessed .docx files in the vault to GFM Markdown via Pandoc. Extracts embedded images.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "register_queue",
        "description": "Scan 00-Inbox/ for files not yet in inbox-queue.json and register them with appropriate agent slots.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _make_logger()
    if name == "clean_filenames":
        n = strip_emoji_filenames(_INBOX, log)
        return f"Cleaned {n} filename(s)"
    if name == "convert_docx":
        ok, failed = process_docx_files(log)
        return f"Converted {ok} docx file(s); {failed} failed"
    if name == "register_queue":
        ok, failed = register_new_files(log)
        return f"Registered {ok} file(s); {failed} failed"

    raise ValueError(f"Unknown tool: {name!r}")
