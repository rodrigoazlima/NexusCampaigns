"""nexus.workers.base - the worker contract (worker-contract.spec.md).

A worker is a plain in-process module: `pending()` (cheap poll, no side
effects) + `handle(item)` (one unit of work, persists its own progress).
No subprocess, no LLM clients anywhere under nexus.workers.

Kinds:
  queue      - polled every runner cycle; `pending()` derives work items
               (inbox-queue slots, mtime scans, missing outputs).
  scheduled  - cron-like; the runner's due-check on `interval_seconds`
               is the only trigger. Queue workers have NO interval.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from nexus.shared.loaders import _find_project_root
from nexus.shared.logger import Logger

_PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)

WORKERS_STATE_ROOT = _PROJECT_ROOT / "system" / "state" / "workers"
MASTER_LOG = _PROJECT_ROOT / "agents" / "runtime" / "state" / "logs" / "automation.log"


@dataclass
class WorkItem:
    key: str                                  # queue rel-key, file path, or "" for scheduled runs
    payload: dict = field(default_factory=dict)


@dataclass
class WorkResult:
    status: Literal["done", "skip", "error"]
    detail: str = ""                          # one-line human summary; goes to the log


@runtime_checkable
class Worker(Protocol):
    name: str
    kind: Literal["queue", "scheduled"]

    def pending(self) -> list[WorkItem]: ...
    def handle(self, item: WorkItem) -> WorkResult: ...


@dataclass
class WorkerConfig:
    name: str
    kind: str = "queue"
    enabled: bool = True
    batch_size: int = 10
    interval_seconds: int = 900               # scheduled kind only; ignored for queue kind
    commit_scope: list[str] = field(default_factory=list)
    options: dict = field(default_factory=dict)


def workers_enabled(registry: dict) -> bool:
    return bool(registry.get("workers_enabled", False))


def load_worker_configs(registry: dict) -> list[WorkerConfig]:
    """Parse the registry.yaml `workers:` block, preserving declared order."""
    configs: list[WorkerConfig] = []
    for name, raw in (registry.get("workers") or {}).items():
        raw = raw or {}
        configs.append(WorkerConfig(
            name=str(name),
            kind=str(raw.get("kind", "queue")),
            enabled=bool(raw.get("enabled", True)),
            batch_size=int(raw.get("batch_size", 10)),
            interval_seconds=int(raw.get("interval_seconds", 900)),
            commit_scope=[str(p) for p in (raw.get("commit_scope") or [])],
            options=dict(raw.get("options") or {}),
        ))
    return configs


def create_worker(cfg: WorkerConfig) -> Worker:
    """Import nexus.workers.<name> and build its worker instance."""
    import importlib
    mod = importlib.import_module(f"nexus.workers.{cfg.name}")
    return mod.create(cfg.options)


def worker_state_dir(name: str) -> Path:
    d = WORKERS_STATE_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_worker_logger(name: str) -> Logger:
    return Logger(
        task_id=name,
        script_basename=name,
        logs_dir=worker_state_dir(name) / "logs",
        master_log=MASTER_LOG,
    )


def adopt_legacy_file(legacy: Path, target: Path) -> None:
    """One-time state migration: copy an old state file to its worker home.

    No-op when the target already exists or the legacy file is gone - the
    legacy dir is deleted with its agent folder, after which this never fires.
    """
    if target.exists() or not legacy.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, target)
