"""signal_bus.py - lightweight file-based inter-agent signal bus.

Signals are advisory and fire-and-forget (G5). The runtime is the only
consumer - agents never read signal files directly.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_MAX_PAYLOAD_BYTES = 1024


class SignalEmitter:
    """Writes signal files to the signal drop directory."""

    def __init__(self, signals_dir: Path) -> None:
        self._dir = signals_dir

    def emit(
        self,
        signal_type: str,
        emitter: str,
        ref: str = "",
        payload: Optional[dict] = None,
    ) -> str:
        """Write a signal file. Returns signal ID."""
        payload = payload or {}
        payload_bytes = json.dumps(payload).encode()
        if len(payload_bytes) > _MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"Signal payload too large ({len(payload_bytes)} > {_MAX_PAYLOAD_BYTES} bytes)"
            )

        signal_id = str(uuid.uuid4())
        data = {
            "id":         signal_id,
            "type":       signal_type,
            "emitter":    emitter,
            "emitted_at": datetime.now(timezone.utc).isoformat(),
            "ref":        ref,
            "payload":    payload,
        }
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{signal_id}.signal.json"
        tmp  = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
        return signal_id


class SignalConsumer:
    """Reads and consumes pending signal files."""

    def __init__(self, signals_dir: Path) -> None:
        self._dir = signals_dir

    def pending(self, signal_type: Optional[str] = None) -> list[dict]:
        """Return all pending signals, optionally filtered by type."""
        if not self._dir.exists():
            return []
        signals = []
        for f in sorted(self._dir.glob("*.signal.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if signal_type is None or data.get("type") == signal_type:
                    signals.append(data)
            except Exception:
                f.unlink(missing_ok=True)  # corrupted signal - discard
        return signals

    def consume(self, signal_id: str) -> None:
        """Delete a consumed signal file."""
        path = self._dir / f"{signal_id}.signal.json"
        path.unlink(missing_ok=True)

    def consume_all(self, signal_type: str) -> list[dict]:
        """Return and delete all pending signals of the given type."""
        signals = self.pending(signal_type)
        for s in signals:
            self.consume(s["id"])
        return signals
