"""review.tools.flag_short_files

Scans 01-Processing/ for draft .md files with fewer than 10 body lines.
Sets needs_reprocessing: true in frontmatter and injects suggestedQuality: 0
when quality: 0 and suggestedQuality is absent.
No LLM. No 02-Library writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import FrontmatterIO, Logger  # noqa: E402

TASK_ID         = "review-agent-short-files"
SCRIPT_BASENAME = "flag_short_files.py"
MIN_BODY_LINES  = 10

_VAULT_ROOT  = _PROJECT_ROOT / "knowledge-base"
_PROCESSING  = _VAULT_ROOT / "01-Processing"
_AGENT_STATE = _AGENTS_DIR / "review" / "state"
_LOGS_DIR    = _AGENT_STATE / "logs"
_MASTER_LOG  = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


def _flag_short_file(path: Path, fio: FrontmatterIO, log: Logger) -> None:
    """Set needs_reprocessing: true and inject suggestedQuality: 0 if applicable."""
    try:
        fm, body = fio.read(path)
        changed = False
        if not fm.get("needs_reprocessing"):
            fm["needs_reprocessing"] = True
            changed = True
        if fm.get("quality", 0) == 0 and "suggestedQuality" not in fm:
            fm["suggestedQuality"] = 0
            changed = True
        if changed:
            fio.write(path, fm, body)
    except Exception as exc:
        log.warning(f"Could not flag {path.name}: {exc}")


def main() -> None:
    log = _make_logger()
    t0  = log.start()
    fio = FrontmatterIO()
    flagged = 0
    scanned = 0

    if not _PROCESSING.exists():
        log.info("01-Processing/ does not exist — nothing to scan")
        log.done(t0, key="processed", count=0, failed=0)
        sys.exit(0)

    for md_path in sorted(_PROCESSING.glob("**/*.md")):
        scanned += 1
        try:
            fm, body = fio.read(md_path)
        except Exception as exc:
            log.warning(f"Read error {md_path.name}: {exc}")
            continue

        body_lines = [ln for ln in body.splitlines() if ln.strip()]
        if len(body_lines) < MIN_BODY_LINES:
            flagged += 1
            log.warning(
                f"Short file ({len(body_lines)} body lines): {md_path.relative_to(_PROJECT_ROOT).as_posix()}"
            )
            _flag_short_file(md_path, fio, log)

    log.info(f"Scanned {scanned} files — {flagged} flagged as short (< {MIN_BODY_LINES} lines)")
    log.done(t0, key="processed", count=flagged, failed=0)
    sys.exit(0)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "scan_short_files",
        "description": (
            "Scan 01-Processing/ for draft .md files with fewer than 10 body lines. "
            "Returns a JSON list of {path, body_lines} objects."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "flag_reprocessing",
        "description": (
            "Set needs_reprocessing: true and inject suggestedQuality: 0 (if quality=0 "
            "and suggestedQuality absent) into the frontmatter of a short file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the .md file"},
            },
            "required": ["path"],
        },
    },
]


def _tool_scan_short_files() -> str:
    import json as _json
    fio = FrontmatterIO()
    results = []
    if not _PROCESSING.exists():
        return _json.dumps([])
    for md_path in sorted(_PROCESSING.glob("**/*.md")):
        try:
            _, body = fio.read(md_path)
            body_lines = [ln for ln in body.splitlines() if ln.strip()]
            if len(body_lines) < MIN_BODY_LINES:
                results.append({
                    "path": str(md_path),
                    "body_lines": len(body_lines),
                })
        except Exception:
            continue
    return _json.dumps(results)


def call_tool(name: str, args: dict, context: dict) -> str:
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _make_logger()
    if name == "scan_short_files":
        return _tool_scan_short_files()
    if name == "flag_reprocessing":
        _flag_short_file(Path(args["path"]), FrontmatterIO(), log)
        return f"Flagged: {args['path']}"

    raise ValueError(f"Unknown tool: {name!r}")
