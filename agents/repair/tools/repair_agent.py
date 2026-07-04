"""repair.tools.repair_agent

Maintenance agent — no LLM, no vault content changes.

Actions (per agent-repair.spec.md):
  ParseErrorPatterns  — scan automation.log (last 24h) for fixable error patterns
  RemoveStaleLock     — delete runner.lock if age > 30 min
  CreateMissingDirs   — ensure all required dirs exist
  ValidateImageRefs   — verify processed-images.json refs by SHA256 identity
  DetectOverdueAgents — flag agents not run within 2 × intervalSeconds
  WriteRepairReport   — emit repair-YYYY-MM-DD.json to reports dir
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from shared import Logger, REQUIRED_DIRS  # noqa: E402
from shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

TASK_ID         = "repair-agent"
SCRIPT_BASENAME = "repair_agent.py"

_ORCH_STATE   = _AGENTS_DIR / "runtime" / "state"
_LOCK_FILE    = _ORCH_STATE / "runner.lock"
_MASTER_LOG   = _ORCH_STATE / "logs" / "automation.log"
_TASKS_STATE  = _ORCH_STATE / "tasks-state.json"
_METRICS_FILE = _ORCH_STATE / "agent-metrics.json"
_AGENT_STATE  = _AGENTS_DIR / "repair" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_REPORTS_DIR  = _AGENTS_DIR / "review" / "state" / "reports"
_QUEUE_FILE   = _PROJECT_ROOT / "system" / "state" / "inbox-queue.json"
_PROC_IMAGES  = _AGENTS_DIR / "vision" / "state" / "processed-images.json"

_LOCK_STALE_S = 1800  # 30 minutes

# Fixable pattern regexes (case-insensitive) → fix label
_ERROR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"stale\s+lock|lock\s+file.*older|runner\.lock", re.I), "stale-lock"),
    (re.compile(r"directory.*not\s+found|cannot\s+find\s+path", re.I),  "missing-directory"),
    (re.compile(r"missing_image_ref", re.I),                             "missing-image-ref"),
]

_MODULE_FILE = Path(__file__)


def _git_update(log: Logger) -> dict:
    """git fetch + git pull --ff-only if project root is a git repo."""
    if not (_PROJECT_ROOT / ".git").exists():
        return {"skipped": True, "reason": "not a git repository"}

    fetch = subprocess.run(
        ["git", "fetch", "--quiet"],
        cwd=str(_PROJECT_ROOT), capture_output=True, text=True
    )
    if fetch.returncode != 0:
        log.warning(f"git fetch failed: {fetch.stderr.strip()}")
        return {"skipped": False, "fetch": "failed", "stderr": fetch.stderr.strip()}

    pull = subprocess.run(
        ["git", "pull", "--ff-only", "--quiet"],
        cwd=str(_PROJECT_ROOT), capture_output=True, text=True
    )
    status = "ok" if pull.returncode == 0 else "failed"
    if pull.returncode != 0:
        log.warning(f"git pull failed: {pull.stderr.strip()}")
    else:
        log.info(f"git pull: {pull.stdout.strip() or 'already up to date'}")
    return {"skipped": False, "fetch": "ok", "pull": status, "output": pull.stdout.strip()}


def _make_logger() -> Logger:
    return Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )


# ---------------------------------------------------------------------------
# ParseErrorPatterns
# ---------------------------------------------------------------------------

def _parse_error_patterns(log: Logger) -> list[str]:
    """Scan automation.log (last 24h) for known fixable error patterns.

    Returns de-duplicated list of fix labels found.
    """
    if not _MASTER_LOG.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    found: set[str] = set()

    try:
        lines = _MASTER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        log.error(f"Cannot read automation.log: {exc}")
        return []

    ts_re = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")

    for line in lines:
        # Filter to last 24h by timestamp prefix
        m = ts_re.match(line)
        if m:
            try:
                ts = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except ValueError:
                pass

        for pattern, label in _ERROR_PATTERNS:
            if pattern.search(line):
                found.add(label)

    if found:
        log.info(f"Error patterns detected: {sorted(found)}")
    return sorted(found)


# ---------------------------------------------------------------------------
# RemoveStaleLock
# ---------------------------------------------------------------------------

def _remove_stale_lock(log: Logger) -> int:
    if not _LOCK_FILE.exists():
        return 0
    try:
        data = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
        locked_at = datetime.fromisoformat(data["startedAt"])
        if locked_at.tzinfo is None:
            locked_at = locked_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - locked_at).total_seconds()
        if age > _LOCK_STALE_S:
            _LOCK_FILE.unlink()
            log.info(f"Removed stale lock (age={age:.0f}s pid={data.get('pid')})")
            return 1
        log.info(f"Lock is fresh (age={age:.0f}s) — skipping")
    except Exception as exc:
        log.warning(f"Cannot inspect lock file: {exc}")
    return 0


# ---------------------------------------------------------------------------
# CreateMissingDirs
# ---------------------------------------------------------------------------

def _create_missing_dirs(log: Logger) -> int:
    created = 0
    for rel in REQUIRED_DIRS:
        d = _PROJECT_ROOT / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            log.info(f"Created missing dir: {rel}")
            created += 1
    return created


# ---------------------------------------------------------------------------
# ValidateImageRefs — SHA256 identity check
# ---------------------------------------------------------------------------

def _sha256_of_file(path: Path) -> str:
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4_194_304), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_image_refs(log: Logger) -> tuple[int, list[str]]:
    """Validate processed-images.json refs by SHA256 identity.

    Returns (repairs_applied, invalid_ref_paths).
    Pruned entries: file missing OR stored sha256 does not match actual file hash.
    """
    if not _PROC_IMAGES.exists():
        return 0, []

    try:
        state: dict[str, Any] = json.loads(_PROC_IMAGES.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error(f"processed-images read error: {exc}")
        return 0, []

    images: dict[str, Any] = state.get("images", {})
    invalid_refs: list[str] = []
    removed = 0

    for key in list(images.keys()):
        entry = images[key]
        rel_path = entry.get("path", "")
        abs_path = _PROJECT_ROOT / rel_path

        if not abs_path.exists():
            # File missing — prune entry
            del images[key]
            invalid_refs.append(rel_path)
            removed += 1
            log.info(f"Pruned missing image ref: {rel_path}")
            continue

        # SHA256 identity check — skip pseudo-keys (path:...)
        if key.startswith("path:"):
            continue

        stored_sha = entry.get("sha256", "")
        if stored_sha:
            try:
                actual_sha = _sha256_of_file(abs_path)
                if actual_sha != stored_sha:
                    log.warning(
                        f"SHA256 mismatch for {rel_path}: "
                        f"stored={stored_sha[:8]}… actual={actual_sha[:8]}…"
                    )
                    invalid_refs.append(rel_path)
                    # Flag entry as failed rather than deleting — preserves audit trail
                    images[key]["status"] = "failed"
                    removed += 1
            except Exception as exc:
                log.warning(f"Cannot hash {rel_path}: {exc}")

    if removed:
        # Rebuild pathIndex from surviving ok/migrated entries
        state["images"] = images
        state["pathIndex"] = {
            v["path"]: k
            for k, v in images.items()
            if not k.startswith("path:")
        }
        tmp = _PROC_IMAGES.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(_PROC_IMAGES)

    return removed, invalid_refs


# ---------------------------------------------------------------------------
# DetectOverdueAgents
# ---------------------------------------------------------------------------

def _detect_overdue_agents(log: Logger) -> list[str]:
    """Flag agents not run within 2 × intervalSeconds."""
    now = datetime.now(timezone.utc)
    overdue: list[str] = []

    # Load last-run timestamps
    tasks_state: dict[str, Any] = {}
    if _TASKS_STATE.exists():
        try:
            tasks_state = json.loads(_TASKS_STATE.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error(f"Cannot read tasks-state.json: {exc}")

    # Collect intervalSeconds from each agent.json
    intervals: dict[str, int] = {}
    for agent_json in _AGENTS_DIR.glob("*/agent.json"):
        try:
            cfg = json.loads(agent_json.read_text(encoding="utf-8"))
            for task_id, task_cfg in cfg.get("tasks", {}).items():
                iv = task_cfg.get("intervalSeconds")
                if iv:
                    intervals[task_id] = int(iv)
        except Exception as exc:
            log.warning(f"Cannot parse {agent_json}: {exc}")

    for task_id, iv in intervals.items():
        entry = tasks_state.get(task_id, {})
        last_run_raw = entry.get("lastRun", "1970-01-01T00:00:00+00:00")
        try:
            last_run = datetime.fromisoformat(last_run_raw)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            elapsed = (now - last_run).total_seconds()
            threshold = 2 * iv
            if elapsed > threshold:
                overdue.append(task_id)
                log.warning(
                    f"Overdue: {task_id} last_run={elapsed:.0f}s ago "
                    f"(threshold={threshold}s)"
                )
        except Exception as exc:
            log.warning(f"Cannot parse lastRun for {task_id}: {exc}")

    return overdue


# ---------------------------------------------------------------------------
# WriteRepairReport
# ---------------------------------------------------------------------------

def _write_repair_report(
    fix_labels: list[str],
    repairs_applied: int,
    overdue_agents: list[str],
    invalid_refs: list[str],
    log: Logger,
    git_update: dict | None = None,
) -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = _REPORTS_DIR / f"repair-{today}.json"

    report = {
        "date":              today,
        "generatedAt":       datetime.now(timezone.utc).isoformat(),
        "gitUpdate":         git_update,
        "fixLabelsDetected": fix_labels,
        "repairsApplied":    repairs_applied,
        "overdueAgents":     overdue_agents,
        "invalidImageRefs":  invalid_refs,
    }

    tmp = report_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(report_path)
    log.info(f"Wrote repair report: {report_path.name}")


# ---------------------------------------------------------------------------
# Standalone entry point (direct execution / testing)
# ---------------------------------------------------------------------------

def main() -> None:
    log = _make_logger()
    t0  = log.start()

    git_result     = _git_update(log)
    fix_labels     = _parse_error_patterns(log)
    repairs        = 0
    repairs       += _remove_stale_lock(log)
    repairs       += _create_missing_dirs(log)
    img_repairs, invalid_refs = _validate_image_refs(log)
    repairs       += img_repairs
    overdue        = _detect_overdue_agents(log)
    _write_repair_report(fix_labels, repairs, overdue, invalid_refs, log, git_update=git_result)

    log.done(t0, key="repairs", count=repairs, failed=0)
    sys.exit(0)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface
# ---------------------------------------------------------------------------

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "git_update",
        "description": (
            "Run git fetch + git pull --ff-only if the project is a git repository. "
            "Call this first, before any repair actions. Failure is non-fatal."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "parse_error_patterns",
        "description": (
            "Scan automation.log (last 24h) for known fixable error patterns. "
            "Returns the list of fix labels detected (stale-lock, missing-directory, missing-image-ref)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remove_stale_lock",
        "description": (
            "Remove runner.lock if it is older than 30 minutes. "
            "Safe to call unconditionally — returns 0 if lock is absent or fresh."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_missing_dirs",
        "description": "Create any required agents/ and system/ subdirectories that do not yet exist.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "validate_image_refs",
        "description": (
            "Validate all entries in processed-images.json by SHA256 identity. "
            "Prunes missing-file entries; flags entries where stored SHA256 does not match the actual file."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "detect_overdue_agents",
        "description": (
            "Check all registered agents against their intervalSeconds. "
            "Returns list of task IDs that have not run within 2 × intervalSeconds."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "write_repair_report",
        "description": (
            "Write a structured repair-YYYY-MM-DD.json report to "
            "agents/review/state/reports/. "
            "Call after all repair actions are complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fix_labels":     {"type": "array",   "items": {"type": "string"}, "description": "Fix labels detected by parse_error_patterns"},
                "repairs_applied": {"type": "integer", "description": "Total number of repairs performed"},
                "overdue_agents": {"type": "array",   "items": {"type": "string"}, "description": "Task IDs flagged as overdue"},
                "invalid_refs":   {"type": "array",   "items": {"type": "string"}, "description": "Image paths with invalid or missing refs"},
            },
            "required": ["fix_labels", "repairs_applied", "overdue_agents", "invalid_refs"],
        },
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    log = _make_logger()

    if name == "git_update":
        return json.dumps(_git_update(log))

    if name == "parse_error_patterns":
        labels = _parse_error_patterns(log)
        return json.dumps({"fixLabelsDetected": labels})

    if name == "remove_stale_lock":
        n = _remove_stale_lock(log)
        return f"Removed {n} stale lock(s)"

    if name == "create_missing_dirs":
        n = _create_missing_dirs(log)
        return f"Created {n} missing director(ies)"

    if name == "validate_image_refs":
        n, invalid = _validate_image_refs(log)
        return json.dumps({"repairsApplied": n, "invalidImageRefs": invalid})

    if name == "detect_overdue_agents":
        overdue = _detect_overdue_agents(log)
        return json.dumps({"overdueAgents": overdue})

    if name == "write_repair_report":
        _write_repair_report(
            fix_labels=args.get("fix_labels", []),
            repairs_applied=args.get("repairs_applied", 0),
            overdue_agents=args.get("overdue_agents", []),
            invalid_refs=args.get("invalid_refs", []),
            log=log,
        )
        return "Repair report written"

    raise ValueError(f"Unknown tool: {name!r}")
