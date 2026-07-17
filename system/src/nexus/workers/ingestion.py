"""nexus.workers.ingestion - vault ingestion (queue producer).

First pipeline stage and the only queue producer: turns raw files dropped
into 00-Inbox/ into inbox-queue entries the consumer workers feed on.
Replaces nexus.tasks.ingestion_agent (BaseAgent lifecycle dropped).

Per file: strip emoji from the filename (idempotent rename) → convert .docx
to GFM Markdown via Pandoc → register the queue entry with per-slot defaults.
Registration is the last step, so a crash before it re-picks the file next
cycle (idempotent). Stray top-level vault entries are absorbed into
00-Inbox/ when ingestion_options.auto_absorb_stray (registry.yaml) is true.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from nexus.shared import (
    AgentSlots,
    AgentSlotStatus,
    FileLock,
    claim_image_hash,
    image_tag,
    locked_update_queue_entry,
)
from nexus.shared.hashing import sha256_of_file
from nexus.shared.logger import Logger
from nexus.shared.loaders import _find_project_root
from nexus.workers.base import (
    WorkItem,
    WorkResult,
    adopt_legacy_file,
    make_worker_logger,
    worker_state_dir,
)

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)
_AGENTS_DIR   = _PROJECT_ROOT / "agents"

IMAGE_EXTS    = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"})
DOCUMENT_EXTS = frozenset({".docx", ".doc", ".pdf", ".md", ".txt", ".odt"})

_VAULT_ROOT   = _PROJECT_ROOT / ".knowledge-base"
_INBOX        = _VAULT_ROOT / "00-Inbox"
_SHARED_STATE = _PROJECT_ROOT / "system" / "state"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"
_IMAGE_HASHES_FILE = _SHARED_STATE / "image-hashes.json"

_REGISTRY_FILE = _AGENTS_DIR / "registry.yaml"

_MAX_ATTEMPTS = 3   # poison-pill guard (worker-contract.spec.md)

# Canonical vault-root folders per CLAUDE.md - anything else at vault root
# is "stray" content that landed outside the pipeline (e.g. a reorganized
# vault, a folder dropped in by hand).
_CANON_VAULT_DIRS = frozenset({
    "00-Inbox", "01-Processing", "02-Library", "03-Campaigns",
    "04-Relationships", "05-Assets", "99-Archive",
})
_STRAY_IGNORE_NAMES = frozenset({"LICENSE", "README.md", ".gitignore"})

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
# Worker state - processed-docx list + per-file attempt counter
# ---------------------------------------------------------------------------

def _processed_docx_file() -> Path:
    return worker_state_dir("ingestion") / "processed-docx.txt"


def _attempts_file() -> Path:
    return worker_state_dir("ingestion") / "attempts.json"


def _load_processed_docx() -> set[str]:
    p = _processed_docx_file()
    if not p.exists():
        return set()
    return {
        ln.strip()
        for ln in p.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }


def _mark_docx_processed(path: Path) -> None:
    rel = path.relative_to(_PROJECT_ROOT).as_posix()
    with open(_processed_docx_file(), "a", encoding="utf-8") as fh:
        fh.write(rel + "\n")


def _load_attempts() -> dict[str, int]:
    p = _attempts_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _bump_attempts(rel: str) -> int:
    attempts = _load_attempts()
    attempts[rel] = attempts.get(rel, 0) + 1
    p = _attempts_file()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(attempts, indent=2), encoding="utf-8")
    tmp.replace(p)
    return attempts[rel]


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------

def _load_queue_raw() -> dict:
    if not _QUEUE_FILE.exists():
        return {}
    try:
        return json.loads(_QUEUE_FILE.read_text(encoding="utf-8").lstrip("﻿"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Emoji stripping
# ---------------------------------------------------------------------------

def _strip_emoji(text: str) -> str:
    """Remove emoji and collapse surrounding whitespace/separators."""
    cleaned = _EMOJI_RE.sub("", text)
    cleaned = re.sub(r"[\s_\-]{2,}", "-", cleaned).strip(" _-")
    return cleaned or text  # never return empty


def _strip_emoji_filename(path: Path, log: Logger) -> Path:
    """Rename one file if its stem contains emoji. Idempotent. Returns final path."""
    if not _EMOJI_RE.search(path.stem):
        return path
    clean_stem = _strip_emoji(path.stem)
    candidate  = path.with_name(clean_stem + path.suffix)
    if candidate == path:
        return path
    if candidate.exists():
        ts        = datetime.now().strftime("%Y%m%d%H%M%S")
        candidate = path.with_name(f"{clean_stem}-{ts}{path.suffix}")
    path.rename(candidate)
    log.info(f"Emoji strip: {path.name!r} → {candidate.name!r}")
    return candidate


# ---------------------------------------------------------------------------
# Pandoc / DOCX conversion
# ---------------------------------------------------------------------------

def _ensure_pandoc(log: Logger) -> bool:
    if shutil.which("pandoc"):
        return True
    log.warning("pandoc not found - attempting: winget install JohnMacFarlane.Pandoc")
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
        pass  # non-empty after move (subdirs) - leave it

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
        pass  # non-fatal - images still exist, paths just need manual fix


# ---------------------------------------------------------------------------
# Stray vault entries (agent-ingestion.spec.md: auto_absorb_stray)
# ---------------------------------------------------------------------------

def find_stray_entries(vault_root: Path) -> list[Path]:
    """Top-level vault entries outside the canonical folder structure."""
    if not vault_root.exists():
        return []
    return [
        entry for entry in sorted(vault_root.iterdir())
        if entry.name not in _CANON_VAULT_DIRS
        and entry.name not in _STRAY_IGNORE_NAMES
        and not entry.name.startswith(".")
    ]


def _auto_absorb_enabled() -> bool:
    try:
        raw = yaml.safe_load(_REGISTRY_FILE.read_text(encoding="utf-8")) or {}
        return bool((raw.get("ingestion_options") or {}).get("auto_absorb_stray", False))
    except Exception:
        return False


def _rewrite_prefix_keys(data: dict, old_prefix: str, new_prefix: str) -> int:
    """Rewrite path-shaped keys/fields starting with old_prefix in place. Returns count changed."""
    changed = 0
    for key in list(data.keys()):
        if isinstance(key, str) and (key == old_prefix or key.startswith(old_prefix + "/")):
            data[new_prefix + key[len(old_prefix):]] = data.pop(key)
            changed += 1
    images = data.get("images")
    if isinstance(images, dict):
        for entry in images.values():
            p = entry.get("path") if isinstance(entry, dict) else None
            if isinstance(p, str) and (p == old_prefix or p.startswith(old_prefix + "/")):
                entry["path"] = new_prefix + p[len(old_prefix):]
                changed += 1
    return changed


def _reindex_moved_prefix(old_prefix: str, new_prefix: str, log: Logger) -> None:
    """Update any existing index (inbox-queue.json, processed-images.json) after a move."""
    for path in (_QUEUE_FILE, _AGENTS_DIR / "vision" / "state" / "processed-images.json"):
        if not path.exists():
            continue
        changed = 0
        with FileLock(path):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            changed = _rewrite_prefix_keys(data, old_prefix, new_prefix)
            if changed:
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
                tmp.replace(path)
        if changed:
            log.info(f"Reindexed {changed} path(s) in {path.name}: {old_prefix} -> {new_prefix}")


def _absorb_stray(src: Path, log: Logger) -> WorkResult:
    dest = _INBOX / src.name
    if dest.exists():
        return WorkResult("skip", f"{dest} already exists")
    old_prefix = src.relative_to(_PROJECT_ROOT).as_posix()
    new_prefix = dest.relative_to(_PROJECT_ROOT).as_posix()
    shutil.move(str(src), str(dest))
    log.info(f"Absorbed stray vault entry: {old_prefix} -> {new_prefix}")
    _reindex_moved_prefix(old_prefix, new_prefix, log)
    return WorkResult("done", f"absorbed {src.name}")


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
    d = AgentSlotStatus.done
    # ingestion is always done (the entry exists because this worker ingested the file).
    # wikilink is a library-stage worker and never runs on inbox items -> skip.
    # review tracks the automated review pass over the draft(s) a file produces.
    if file_type == "image":
        return AgentSlots(ingestion=d, vision=p, lore=p, classification=p,
                          wiki=s, wikilink=s, token=p, review=p)
    if file_type == "document":
        return AgentSlots(ingestion=d, vision=s, lore=s, classification=p,
                          wiki=p, wikilink=s, token=s, review=p)
    return AgentSlots(ingestion=d, vision=s, lore=s, classification=s,
                      wiki=s, wikilink=s, token=s, review=s)


def _is_token_file(p: Path) -> bool:
    """Return True for generated token files (not original source images)."""
    stem = p.stem
    return stem.endswith("-token") or ".token" in stem


def _register_file(path: Path, log: Logger, *, img_hash: Optional[str] = None) -> None:
    rel = path.relative_to(_PROJECT_ROOT).as_posix()
    ft = _file_type(path)
    payload = {
        "ingestedAt": datetime.now(timezone.utc).isoformat(),
        "type":       ft,
        "agents":     _make_slots(ft).model_dump(mode="json"),
    }
    if img_hash:
        payload["imageHash"] = img_hash

    def _apply(entry: dict) -> Optional[str]:
        entry.update(payload)
        return None

    locked_update_queue_entry(_QUEUE_FILE, rel, _apply)
    log.info(f"Queued [{ft}]{image_tag(sha256=img_hash, path=rel)}")


def _register_duplicate_image(path: Path, original: dict, img_hash: str, log: Logger) -> None:
    """Register a content-identical image: the file itself is kept - 00-Inbox/
    is never modified or deleted from (vault hard rule) - but every downstream
    agent slot is skipped so vision/classification/lore/token never produce a
    second draft for a picture that already has one.
    """
    rel = path.relative_to(_PROJECT_ROOT).as_posix()
    skip = AgentSlotStatus.skip
    payload = {
        "ingestedAt": datetime.now(timezone.utc).isoformat(),
        "type":       "image",
        "agents":     AgentSlots(
            ingestion=AgentSlotStatus.done, vision=skip, lore=skip,
            classification=skip, wiki=skip, wikilink=skip, token=skip, review=skip,
        ).model_dump(mode="json"),
        "imageHash":       img_hash,
        "duplicateOfPath": original.get("path"),
    }

    def _apply(entry: dict) -> Optional[str]:
        entry.update(payload)
        return None

    locked_update_queue_entry(_QUEUE_FILE, rel, _apply)
    log.warning(
        f"Duplicate image ingested: content-identical to "
        f"{original.get('path')} (first seen "
        f"{original.get('firstSeenAt', 'unknown')}) - queued but all "
        f"downstream agent slots skipped{image_tag(sha256=img_hash, path=rel)}"
    )


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class IngestionWorker:
    name = "ingestion"
    kind = "queue"

    def __init__(self, options: dict | None = None) -> None:
        (_INBOX / "docs").mkdir(parents=True, exist_ok=True)
        (_INBOX / "images").mkdir(parents=True, exist_ok=True)
        adopt_legacy_file(
            _SHARED_STATE / "ingestion" / "processed-docx.txt",
            _processed_docx_file(),
        )
        self._pandoc_ok: bool | None = None   # resolved once per instance

    def pending(self) -> list[WorkItem]:
        items: list[WorkItem] = []
        attempts = _load_attempts()

        # Stray top-level vault entries (absorbed or logged, one item each)
        for stray in find_stray_entries(_VAULT_ROOT):
            rel = stray.relative_to(_PROJECT_ROOT).as_posix()
            items.append(WorkItem(rel, {"action": "absorb"}))

        # Inbox files not yet registered in the queue
        if _INBOX.exists():
            queue = _load_queue_raw()
            for f in sorted(_INBOX.rglob("*")):
                if not f.is_file() or _is_token_file(f):
                    continue
                rel = f.relative_to(_PROJECT_ROOT).as_posix()
                if rel in queue or attempts.get(rel, 0) >= _MAX_ATTEMPTS:
                    continue
                items.append(WorkItem(rel, {"action": "ingest"}))

        # Unconverted .docx living outside 00-Inbox (vault-wide sweep)
        processed = _load_processed_docx()
        for p in _VAULT_ROOT.rglob("*.docx"):
            if ".git" in p.parts or "agents" in p.parts:
                continue
            rel = p.relative_to(_PROJECT_ROOT).as_posix()
            if rel in processed or attempts.get(rel, 0) >= _MAX_ATTEMPTS:
                continue
            if any(i.key == rel for i in items):
                continue  # already picked up as an inbox item
            items.append(WorkItem(rel, {"action": "docx"}))

        return items

    def handle(self, item: WorkItem) -> WorkResult:
        log = make_worker_logger(self.name)
        path = _PROJECT_ROOT / item.key
        action = item.payload.get("action", "ingest")

        if action == "absorb":
            if not path.exists():
                return WorkResult("skip", "stray entry gone")
            if not _auto_absorb_enabled():
                log.warning(f"Stray vault entry outside 00-Inbox (auto_absorb_stray disabled): {path.name}")
                return WorkResult("skip", "auto_absorb_stray disabled")
            return _absorb_stray(path, log)

        if not path.exists():
            return WorkResult("skip", "file gone")

        if action == "docx" or path.suffix.lower() == ".docx":
            if self._pandoc_ok is None:
                self._pandoc_ok = _ensure_pandoc(log)
            if not self._pandoc_ok:
                _bump_attempts(item.key)
                return WorkResult("error", "pandoc unavailable - DOCX conversion skipped")

        # 1. Emoji strip (rename changes the queue key going forward)
        path = _strip_emoji_filename(path, log)

        # 2. DOCX → GFM Markdown (output .md is registered on the next cycle)
        if path.suffix.lower() == ".docx":
            out = _convert_docx(path, log)
            if out is None:
                _bump_attempts(item.key)
                return WorkResult("error", f"pandoc conversion failed: {path.name}")
            _mark_docx_processed(path)

        # 3. Register queue entry - last step, so a crash before it re-picks
        #    the file next cycle
        if action == "ingest":
            if _file_type(path) == "image":
                # Content-hash dedup: this is the single queue producer every
                # inbox file funnels through (dashboard upload or a raw
                # filesystem drop alike), so this is the one place a check
                # here catches every duplicate regardless of how it arrived -
                # see nexus.shared.image_hashes for why the dashboard's own
                # pre-write check alone isn't enough.
                img_hash = sha256_of_file(path)
                rel = path.relative_to(_PROJECT_ROOT).as_posix()
                dup = claim_image_hash(_IMAGE_HASHES_FILE, img_hash, rel)
                if dup is not None:
                    _register_duplicate_image(path, dup, img_hash, log)
                    return WorkResult("done", f"duplicate of {dup.get('path')}")
                _register_file(path, log, img_hash=img_hash)
            else:
                _register_file(path, log)
            return WorkResult("done", f"registered {path.name}")
        return WorkResult("done", f"converted {path.name}")


def create(options: dict | None = None) -> IngestionWorker:
    return IngestionWorker(options)


if __name__ == "__main__":
    worker = create()
    for _item in worker.pending():
        _res = worker.handle(_item)
        print(f"{_res.status} {_item.key}: {_res.detail}")
