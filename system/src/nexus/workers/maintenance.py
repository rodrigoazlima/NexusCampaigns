"""nexus.workers.maintenance — pipeline self-healing (scheduled + signal-triggered).

Replaces nexus.tasks.repair_agent. Runs daily, or immediately after any
worker item errors (worker-error signal, consumed by the runner loop).

Actions (each isolated — a failure never blocks the others):
  GitUpdate                  — git fetch + pull --ff-only
  ParseErrorPatterns         — scan automation.log (last 24h) for fixable patterns
  RemoveStaleLock            — delete runner.lock if age > 30 min
  GenerateMissingAgentConfigs— scaffold agent.json for LLM agents only
  CreateMissingDirs          — ensure REQUIRED_DIRS exist
  EnsureAgentScaffold        — prompts/ + state/ dirs for LLM agents only
  EnsureAgentRelationLinks   — junctions for LLM/planned agents only
  ValidateImageRefs          — verify processed-images.json refs by SHA256
  ValidateInboxQueue         — prune gone-file entries, backfill missing slots,
                               reset resolvable error slots (reruns < 3),
                               report poison pills (error slots, reruns >= 3)
  DetectOverdueAgents        — LLM agents by agent.json interval,
                               workers by registry workers: interval
  CheckDashboardHealth       — TCP + HTTP probe
  WriteRepairReport          — system/state/workers/maintenance/reports/
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nexus.shared import Logger, REQUIRED_DIRS, image_tag, sha256_of_file
from nexus.shared.loaders import _find_project_root
from nexus.workers.base import (
    MASTER_LOG,
    WorkItem,
    WorkResult,
    make_worker_logger,
    worker_state_dir,
)

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)
_AGENTS_DIR   = _PROJECT_ROOT / "agents"

_ORCH_STATE   = _AGENTS_DIR / "runtime" / "state"
_LOCK_FILE    = _ORCH_STATE / "runner.lock"
_TASKS_STATE  = _ORCH_STATE / "tasks-state.json"
_QUEUE_FILE   = _PROJECT_ROOT / "system" / "state" / "inbox-queue.json"
_PROC_IMAGES  = _AGENTS_DIR / "vision" / "state" / "processed-images.json"
_ENV_FILE     = _PROJECT_ROOT / "system" / ".env.local"
_REGISTRY     = _AGENTS_DIR / "registry.yaml"

_LOCK_STALE_S        = 1800  # 30 minutes
_DASHBOARD_PORT      = 48080  # fallback if PORT missing from .env.local
_DASHBOARD_TIMEOUT_S = 3
_MAX_RERUNS          = 3     # poison-pill threshold (worker-contract.spec.md)

# Fixable pattern regexes (case-insensitive) → fix label
_ERROR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"stale\s+lock|lock\s+file.*older|runner\.lock", re.I), "stale-lock"),
    (re.compile(r"directory.*not\s+found|cannot\s+find\s+path", re.I),  "missing-directory"),
    (re.compile(r"missing_image_ref", re.I),                             "missing-image-ref"),
]


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


# ---------------------------------------------------------------------------
# ParseErrorPatterns
# ---------------------------------------------------------------------------

def _parse_error_patterns(log: Logger) -> list[str]:
    """Scan automation.log (last 24h) for known fixable error patterns.

    Returns de-duplicated list of fix labels found.
    """
    if not MASTER_LOG.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    found: set[str] = set()

    try:
        lines = MASTER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
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
# GenerateMissingAgentConfigs — LLM agents only. agent.json is gitignored
# (machine-local dispatch config); a fresh clone has none, so runner.py's
# agents/*/agent.json glob discovers zero LLM tasks. Static tasks are
# workers now — configured in registry.yaml, nothing to regenerate.
# ---------------------------------------------------------------------------

_AGENT_JSON_SPECS: dict[str, list[dict]] = {
    "vision": [
        {"task_id": "vision-agent", "model": "claude-sonnet-4-6",
         "tools_module": "vision.tools.classify_images", "interval": 900,
         "description": "Image classification via local vision LLM."},
    ],
    "lore": [
        {"task_id": "lore-agent", "model": "claude-sonnet-4-6",
         "tools_module": "lore.tools.generate_npcs", "interval": 900,
         "description": "Generate NPC drafts from classified images."},
    ],
    "classification": [
        {"task_id": "classification-agent", "model": "claude-haiku-4-5-20251001",
         "tools_module": "classification.tools.enrich_tags", "interval": 900,
         "description": "Enrich draft tags and infer entity type.",
         "llm": {"text_model": "qwen/qwen3.5-9b", "vision_model": "qwen3-vl-4b-instruct"}},
    ],
    "wiki": [
        {"task_id": "wiki-agent", "model": "claude-sonnet-4-6",
         "tools_module": "wiki.tools.compile_wiki", "interval": 900,
         "description": "Compile enriched drafts into wiki entity pages."},
    ],
}


def _generate_missing_agent_configs(log: Logger) -> int:
    """Scaffold agents/<name>/agent.json from _AGENT_JSON_SPECS when absent."""
    created = 0
    for agent_name, tasks in _AGENT_JSON_SPECS.items():
        agent_json = _AGENTS_DIR / agent_name / "agent.json"
        if agent_json.exists():
            continue
        payload: dict[str, Any] = {"tasks": {}}
        for t in tasks:
            dispatch = {
                "type": "claude-api",
                "claude_api": {
                    "model": t["model"],
                    "tools_module": t["tools_module"],
                    "prompt_file": t.get("prompt_file", "prompts/system.md"),
                },
            }
            task_payload: dict[str, Any] = {
                "intervalSeconds": t["interval"],
                "description": t["description"],
                "dispatch": dispatch,
            }
            if "llm" in t:
                task_payload["llm"] = t["llm"]
            payload["tasks"][t["task_id"]] = task_payload
        agent_json.parent.mkdir(parents=True, exist_ok=True)
        agent_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info(f"Generated missing agent.json: agents/{agent_name}/agent.json")
        created += 1
    return created


# ---------------------------------------------------------------------------
# CreateMissingDirs + agent scaffold (LLM agents only)
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


def _ensure_agent_scaffold(log: Logger) -> int:
    """LLM agents get a real prompts/ and state/ dir. Creates only what's
    missing — never touches an existing one."""
    created = 0
    for agent_name in _AGENT_JSON_SPECS:
        agent_root = _AGENTS_DIR / agent_name
        if not agent_root.is_dir():
            continue
        for sub in ("prompts", "state"):
            p = agent_root / sub
            if not p.exists():
                p.mkdir(parents=True, exist_ok=True)
                log.info(f"Agent scaffold: created {agent_name}/{sub}")
                created += 1
    return created


# ---------------------------------------------------------------------------
# EnsureAgentRelationLinks — mirrors setup-service.ps1's Ensure-AgentRelationLinks
# (see docs/specs/agents/agent-relationships.md). LLM + planned agents only —
# static agents are workers now and have no folders. Only creates a junction
# where the path is completely absent (a destroyed link) — never touches a
# path that already exists.
#
# Every generated mount's top path segment is dot-prefixed by convention
# (.knowledge-base, .agents, .system, ...) so a single .gitignore block can
# prune reparse-point-unaware walks. Keep in sync with setup-service.ps1.
# ---------------------------------------------------------------------------

_AGENT_RELATIONS: dict[str, list[str]] = {
    "adventure-builder": [".knowledge-base/02-Library", ".knowledge-base/03-Campaigns", "agents/lore", "agents/canon", "agents/relationship"],
    "canon":             [".knowledge-base/02-Library"],
    "classification":    [".knowledge-base/00-Inbox", ".knowledge-base/01-Processing", ".knowledge-base/02-Library"],
    "curator":           [".knowledge-base/01-Processing"],
    "deduplication":     [".knowledge-base/00-Inbox", ".knowledge-base/01-Processing", ".knowledge-base/02-Library"],
    "encounter-builder": [".knowledge-base/02-Library", ".knowledge-base/03-Campaigns"],
    "lore":              [".knowledge-base/00-Inbox", ".knowledge-base/01-Processing", ".knowledge-base/02-Library", "agents/vision", "system/state"],
    "relationship":      [".knowledge-base/02-Library", ".knowledge-base/04-Relationships"],
    "search":            [".knowledge-base/01-Processing", ".knowledge-base/02-Library"],
    "session-builder":   [".knowledge-base/03-Campaigns", "agents/adventure-builder"],
    "vision":            [".knowledge-base/00-Inbox", ".knowledge-base/01-Processing", "system/state"],
    "wiki":              [".knowledge-base/01-Processing", ".knowledge-base/02-Library", "system/state"],
}


def _ensure_agent_relation_links(log: Logger) -> int:
    created = 0
    all_agents = sorted(
        p.name for p in _AGENTS_DIR.iterdir()
        if p.is_dir() and p.name not in {"tests", "shared"}
    )

    for agent_name, rels in _AGENT_RELATIONS.items():
        agent_root = _AGENTS_DIR / agent_name
        if not agent_root.exists():
            continue

        # Every agent also gets system/state regardless of its table entry
        # ("system" already covers state/ — skip the overlap).
        extra = ["system/state"] if "system" not in rels else []
        for rel in extra + rels:
            targets = (
                [f"agents/{a}" for a in all_agents if a != agent_name]
                if rel == "agents/*" else [rel]
            )
            for t in targets:
                # t's first segment may already be dot-prefixed (".knowledge-base/...")
                # or plain ("agents/...", "system/..."). The real vault root lives on
                # disk as ".knowledge-base"; "agents" and "system" are real, unprefixed
                # top-level folders. The per-agent MOUNT name is always dot-prefixed.
                head, _, tail = t.partition("/")
                logical = head.lstrip(".")
                target_first = ".knowledge-base" if logical == "knowledge-base" else logical
                target_path = _PROJECT_ROOT / Path(target_first) / Path(tail.replace("/", os.sep)) if tail else _PROJECT_ROOT / target_first
                link_rel = (Path(f".{logical}") / tail.replace("/", os.sep)) if tail else Path(f".{logical}")
                link_path = agent_root / link_rel

                if link_path.exists():
                    continue  # intact link, real dir, or file — never touch it
                if not target_path.exists():
                    continue  # nothing to link to (yet)

                link_path.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    log.info(f"Recreated missing link: {agent_name}/{link_rel.as_posix()}")
                    created += 1
                else:
                    log.warning(
                        f"Could not recreate link {agent_name}/{link_rel.as_posix()}: "
                        f"{result.stderr.strip() or result.stdout.strip()}"
                    )
    return created


# ---------------------------------------------------------------------------
# ValidateImageRefs — SHA256 identity check
# ---------------------------------------------------------------------------

_sha256_of_file = sha256_of_file


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
            log.info(f"Pruned missing image ref{image_tag(uuid=entry.get('uuid'), path=rel_path)}")
            continue

        # SHA256 identity check — skip pseudo-keys (path:...)
        if key.startswith("path:"):
            continue

        stored_sha = entry.get("sha256", "")
        if stored_sha:
            try:
                actual_sha = _sha256_of_file(abs_path)
                if actual_sha != stored_sha:
                    # The path was reused for different bytes since this entry was
                    # written (e.g. a slug-collision rename) — the ledger's identity
                    # for this path is now wrong, not just out of date.
                    log.warning(
                        f"SHA256 mismatch: stored={stored_sha[:8]}… actual={actual_sha[:8]}…"
                        f"{image_tag(uuid=entry.get('uuid'), path=rel_path)}"
                    )
                    invalid_refs.append(rel_path)
                    # Flag entry as failed rather than deleting — preserves audit trail
                    images[key]["status"] = "failed"
                    removed += 1
            except Exception as exc:
                log.warning(f"Cannot hash image: {exc}{image_tag(uuid=entry.get('uuid'), path=rel_path)}")

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
# ValidateInboxQueue — prune gone files, backfill slots, reset resolvable
# error slots, collect poison pills
# ---------------------------------------------------------------------------

def _validate_inbox_queue(log: Logger) -> tuple[int, list[str], list[dict]]:
    """Validate inbox-queue.json.

    - Prunes entries whose file no longer exists on disk (nothing else ever
      shrinks the queue back to reality).
    - Backfills missing agent slots through AgentSlots defaults (schema
      evolution — moved here from the old ingestion batch task).
    - Resets slots stuck at 'error' with reruns < 3 back to 'pending' and
      increments reruns.<slot> (the underlying file exists, so the cause may
      be resolved — worth a retry).
    - Collects poison pills: error slots with reruns >= 3, for the report.

    Returns (repairs_applied, pruned_paths, poison_pills).
    """
    if not _QUEUE_FILE.exists():
        return 0, [], []

    try:
        queue: dict[str, Any] = json.loads(
            _QUEUE_FILE.read_text(encoding="utf-8").lstrip("﻿")
        )
    except Exception as exc:
        log.error(f"inbox-queue read error: {exc}")
        return 0, [], []

    from nexus.shared import AgentSlots, AgentSlotStatus

    pruned: list[str] = []
    poison: list[dict] = []
    repairs = 0
    changed = False

    for rel_path in list(queue.keys()):
        if not (_PROJECT_ROOT / rel_path).exists():
            del queue[rel_path]
            pruned.append(rel_path)
            changed = True
            log.info(f"Pruned missing inbox-queue ref: {rel_path}")
            continue

        entry = queue[rel_path]
        if not isinstance(entry, dict):
            continue

        # Backfill missing slots in canonical field order
        old_agents = entry.get("agents", {})
        try:
            new_agents = AgentSlots.model_validate(old_agents).model_dump(mode="json")
            new_agents["ingestion"] = AgentSlotStatus.done.value  # entry exists => ingested
            if new_agents != old_agents:
                entry["agents"] = new_agents
                repairs += 1
                changed = True
        except Exception:
            new_agents = old_agents

        # Error-slot reset / poison-pill collection
        reruns = entry.setdefault("reruns", {})
        for slot, status in list(entry.get("agents", {}).items()):
            if status != "error":
                continue
            n = int(reruns.get(slot, 0))
            if n < _MAX_RERUNS:
                entry["agents"][slot] = "pending"
                reruns[slot] = n + 1
                repairs += 1
                changed = True
                log.info(f"Reset error slot {slot} → pending ({rel_path}, rerun {n + 1})")
            else:
                poison.append({"path": rel_path, "slot": slot, "reruns": n})

    if changed:
        tmp = _QUEUE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(queue, indent=2, default=str), encoding="utf-8")
        tmp.replace(_QUEUE_FILE)

    if poison:
        log.warning(f"Poison-pill queue slots (reruns >= {_MAX_RERUNS}): {len(poison)}")

    return len(pruned) + repairs, pruned, poison


# ---------------------------------------------------------------------------
# DetectOverdueAgents — LLM agents (agent.json) + workers (registry.yaml)
# ---------------------------------------------------------------------------

def _load_registry_raw() -> dict:
    if not _REGISTRY.exists():
        return {}
    try:
        import yaml as _yaml
        return _yaml.safe_load(_REGISTRY.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _detect_overdue_agents(log: Logger) -> list[str]:
    """Flag LLM agents and scheduled workers not run within 2 × their interval."""
    now = datetime.now(timezone.utc)
    overdue: list[str] = []

    tasks_state: dict[str, Any] = {}
    if _TASKS_STATE.exists():
        try:
            tasks_state = json.loads(_TASKS_STATE.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error(f"Cannot read tasks-state.json: {exc}")

    # LLM agents: intervalSeconds from each agent.json
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

    # Scheduled workers: interval_seconds from registry.yaml workers: block.
    # Queue workers poll every cycle and have no interval — not checked here.
    for name, raw in (_load_registry_raw().get("workers") or {}).items():
        raw = raw or {}
        if raw.get("kind") == "scheduled" and raw.get("enabled", True):
            intervals[f"worker:{name}"] = int(raw.get("interval_seconds", 900))

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
# CheckDashboardHealth
# ---------------------------------------------------------------------------

def _read_dashboard_port(log: Logger) -> int:
    """Read PORT from system/.env.local (written by setup-service.ps1)."""
    if not _ENV_FILE.exists():
        return _DASHBOARD_PORT
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PORT="):
                return int(line.split("=", 1)[1].strip())
    except Exception as exc:
        log.warning(f"Cannot read PORT from {_ENV_FILE.name}: {exc}")
    return _DASHBOARD_PORT


def _check_dashboard_health(log: Logger) -> dict:
    """Check dashboard TCP port + HTTP response. No LLM, no side effects."""
    port = _read_dashboard_port(log)
    result: dict[str, Any] = {"port": port, "portListening": False, "httpStatus": None, "healthy": False}

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(_DASHBOARD_TIMEOUT_S)
        try:
            sock.connect(("127.0.0.1", port))
            result["portListening"] = True
        except OSError as exc:
            log.warning(f"Dashboard port {port} not listening: {exc}")
            return result

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}", method="GET")
        with urllib.request.urlopen(req, timeout=_DASHBOARD_TIMEOUT_S) as resp:
            result["httpStatus"] = resp.status
            result["healthy"] = 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        result["httpStatus"] = exc.code
        log.warning(f"Dashboard HTTP error: {exc.code}")
    except Exception as exc:
        log.warning(f"Dashboard HTTP probe failed: {exc}")

    if result["healthy"]:
        log.info(f"Dashboard healthy on port {port} (HTTP {result['httpStatus']})")
    return result


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
    dashboard_health: dict | None = None,
    pruned_queue_refs: list[str] | None = None,
    poison_pills: list[dict] | None = None,
) -> Path:
    reports_dir = worker_state_dir("maintenance") / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = reports_dir / f"repair-{today}.json"

    report = {
        "date":              today,
        "generatedAt":       datetime.now(timezone.utc).isoformat(),
        "gitUpdate":         git_update,
        "fixLabelsDetected": fix_labels,
        "repairsApplied":    repairs_applied,
        "overdueAgents":     overdue_agents,
        "invalidImageRefs":  invalid_refs,
        "prunedInboxQueueRefs": pruned_queue_refs or [],
        "poisonPillSlots":   poison_pills or [],
        "dashboardHealth":   dashboard_health,
    }

    tmp = report_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(report_path)
    log.info(f"Wrote repair report: {report_path.name}")
    return report_path


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _run_step(log: Logger, name: str, fn, default):
    """Run one repair step in isolation — a failure here must never block the
    other steps (in particular CreateMissingDirs, downstream of several
    steps that touch the filesystem/network/git and can raise)."""
    try:
        return fn()
    except Exception as exc:
        log.error(f"Repair step {name!r} failed — continuing with other steps: {exc}")
        return default


class MaintenanceWorker:
    name = "maintenance"
    kind = "scheduled"

    def __init__(self, options: dict | None = None) -> None:
        pass

    def pending(self) -> list[WorkItem]:
        return [WorkItem("", {})]

    def handle(self, item: WorkItem) -> WorkResult:
        log = make_worker_logger(self.name)
        t0  = log.start()

        git_result = _run_step(log, "git_update", lambda: _git_update(log),
                                {"skipped": True, "reason": "step raised"})
        fix_labels = _run_step(log, "parse_error_patterns", lambda: _parse_error_patterns(log), [])

        repairs  = 0
        repairs += _run_step(log, "remove_stale_lock", lambda: _remove_stale_lock(log), 0)
        repairs += _run_step(log, "generate_missing_agent_configs", lambda: _generate_missing_agent_configs(log), 0)
        repairs += _run_step(log, "create_missing_dirs", lambda: _create_missing_dirs(log), 0)
        repairs += _run_step(log, "ensure_agent_scaffold", lambda: _ensure_agent_scaffold(log), 0)
        repairs += _run_step(log, "ensure_agent_relation_links", lambda: _ensure_agent_relation_links(log), 0)

        img_repairs, invalid_refs = _run_step(log, "validate_image_refs", lambda: _validate_image_refs(log), (0, []))
        repairs += img_repairs

        queue_repairs, pruned_queue_refs, poison = _run_step(
            log, "validate_inbox_queue", lambda: _validate_inbox_queue(log), (0, [], []))
        repairs += queue_repairs

        overdue   = _run_step(log, "detect_overdue_agents", lambda: _detect_overdue_agents(log), [])
        dashboard = _run_step(log, "check_dashboard_health", lambda: _check_dashboard_health(log),
                               {"port": None, "portListening": False, "httpStatus": None, "healthy": False})

        try:
            _write_repair_report(fix_labels, repairs, overdue, invalid_refs, log,
                                 git_update=git_result, dashboard_health=dashboard,
                                 pruned_queue_refs=pruned_queue_refs, poison_pills=poison)
        except Exception as exc:
            log.done(t0, key="repairs", count=repairs, failed=1)
            return WorkResult("error", f"cannot write repair report: {exc}")

        log.done(t0, key="repairs", count=repairs, failed=0)
        return WorkResult("done", f"repairs={repairs} overdue={len(overdue)} poison={len(poison)}")


def create(options: dict | None = None) -> MaintenanceWorker:
    return MaintenanceWorker(options)


if __name__ == "__main__":
    worker = create()
    for _item in worker.pending():
        _res = worker.handle(_item)
        print(f"{_res.status}: {_res.detail}")
