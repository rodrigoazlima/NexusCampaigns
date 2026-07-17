"""nexus.workers - in-process static workers (no LLM, no subprocess).

Public surface: the contract types in base. Worker modules are imported
lazily by name via base.create_worker - never import one worker from another.
"""

from .base import (
    WorkItem,
    WorkResult,
    Worker,
    WorkerConfig,
    create_worker,
    load_worker_configs,
    make_worker_logger,
    worker_state_dir,
    workers_enabled,
)

__all__ = [
    "WorkItem", "WorkResult", "Worker", "WorkerConfig",
    "create_worker", "load_worker_configs", "make_worker_logger",
    "worker_state_dir", "workers_enabled",
]
