"""nexus.runtime.signals - cross-checks pending signal-bus entries against
each task's signal_triggers to force an immediate (out-of-interval) dispatch."""

from __future__ import annotations

from nexus.shared import Logger, TaskDispatchEntry
from nexus.shared.signal_bus import SignalConsumer

from .paths import SIGNALS_DIR


def check_signals(
    tasks: list[tuple[str, TaskDispatchEntry]],
    log: Logger,
) -> set[str]:
    """Return task_ids that should run immediately due to pending signals."""
    consumer = SignalConsumer(SIGNALS_DIR)
    triggered: set[str] = set()

    for task_id, entry in tasks:
        triggers = list(getattr(entry, "signal_triggers", None) or [])
        for signal_type in triggers:
            pending = consumer.pending(signal_type)
            if pending:
                log.info(
                    f"Signal '{signal_type}' pending ({len(pending)} item(s)) - "
                    f"triggering {task_id} immediately"
                )
                triggered.add(task_id)
                break

    return triggered
