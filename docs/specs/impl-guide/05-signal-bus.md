# Impl: File-Based Signal Bus

**Phase:** P3  
**Priority:** Medium  
**Effort:** 2 days  
**Depends on:** runner.py (exists), agent.json dispatch schema (exists)

---

## Problem

Agents poll on fixed intervals (typically 3600s). A Vision Agent that classifies an image at 08:00 does not trigger the Lore Agent until Lore's 1-hour interval fires - potentially 59 minutes later. The classified image is immediately ready for NPC generation. The 59-minute gap is pure scheduling lag, not work.

More broadly: inter-agent data dependencies are implicit (shared filesystem) and invisible to the runtime. The scheduler has no way to know "vision-agent completed a classification that lore-agent needs."

---

## Goal

Agents can emit typed signals after completing work. The runtime checks for pending signals at each scheduler cycle and immediately dispatches dependent agents whose signal dependency is satisfied - without waiting for their interval.

Signals are:
- **Fire-and-forget:** emitting agent has no knowledge of whether signal was consumed
- **File-based:** no message queue infrastructure needed
- **Typed:** each signal has a `type` string consumed agents can filter on
- **Single-consume:** a signal file is deleted after the dependent agent is dispatched on it

---

## Design Principles

1. Simplest possible implementation - file drop in a watched directory
2. No new dependencies (no Redis, no Kafka, no SQLite queue)
3. Signal loss is acceptable - dependent agent will run on its next interval anyway (signals accelerate, not enable)
4. Signals do not carry large payloads - only metadata (type, emitter, timestamp, optional ref)
5. The runtime is the only consumer of signals - agents never read signal files

---

## Scope

Files to create:
- `agents/runtime/state/signals/` - signal drop directory (created at runtime startup)
- `agents/shared/signal_bus.py` - `SignalEmitter` and `SignalConsumer` classes
- `agents/tests/test_signal_bus.py`

Files to modify:
- `agents/runtime/tools/runner.py` - call `_check_signals()` at start of each cycle
- `agents/shared/interfaces.py` - `ISignalEmitter` protocol
- `agent.json` schema - add optional `signal_triggers` array to task config

---

## Signal File Format

`agents/runtime/state/signals/{uuid}.signal.json`:

```json
{
  "id":         "a3f9c2d1-...",
  "type":       "image-classified",
  "emitter":    "vision-agent",
  "emitted_at": "2026-06-10T08:05:12Z",
  "ref":        "npc-warrior-portrait-001.png",
  "payload":    {}
}
```

- `id` - UUID4, used as filename; guarantees no collision
- `type` - string; consuming agents declare which types trigger them
- `emitter` - task_id of the emitting agent
- `ref` - optional reference (image path, slug, etc.) for logging
- `payload` - optional small metadata dict (max 1KB enforced by emitter)

---

## `agent.json` Schema Extension

Add optional `signal_triggers` array to task config:

```json
{
  "tasks": {
    "lore-agent": {
      "intervalSeconds": 3600,
      "description": "NPC sheet generation from images x scenarios",
      "signal_triggers": ["image-classified"],
      "dispatch": { ... }
    }
  }
}
```

And optional `emits_signals` array (for documentation and dependency graph):

```json
{
  "tasks": {
    "vision-agent": {
      "intervalSeconds": 3600,
      "description": "Image classification via local vision LLM",
      "emits_signals": ["image-classified"],
      "dispatch": { ... }
    }
  }
}
```

`emits_signals` is documentation only - agents emit signals via code, not config. `signal_triggers` is functional - the runtime reads it.

---

## `shared/signal_bus.py`

```python
"""signal_bus.py - lightweight file-based inter-agent signal bus."""

from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_MAX_PAYLOAD_BYTES = 1024


class SignalEmitter:
    """Emits signal files to the signal drop directory."""

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
        """Return and delete all pending signals of a given type."""
        signals = self.pending(signal_type)
        for s in signals:
            self.consume(s["id"])
        return signals
```

---

## Runner Changes (`runtime/tools/runner.py`)

### Signal directory setup

```python
_SIGNALS_DIR = _RUNTIME_STATE / "signals"
```

Create on startup alongside `_LOGS_DIR`.

### `_check_signals()` at cycle start

```python
def _check_signals(
    tasks: list[tuple[str, TaskDispatchEntry]],
    log: _Logger,
) -> set[str]:
    """Return set of task_ids that should run immediately due to pending signals."""
    consumer = SignalConsumer(_SIGNALS_DIR)
    triggered: set[str] = set()

    for task_id, entry in tasks:
        triggers = getattr(entry, "signal_triggers", []) or []
        for signal_type in triggers:
            pending = consumer.pending(signal_type)
            if pending:
                log.info(
                    f"Signal '{signal_type}' pending ({len(pending)} items) - "
                    f"triggering {task_id} immediately"
                )
                triggered.add(task_id)
                break  # one trigger type is enough to schedule the task

    return triggered
```

### `run_cycle()` integration

```python
def run_cycle(self, task_filter: Optional[str] = None) -> None:
    self.reload()
    signal_triggered = _check_signals(self._tasks, self._log)

    for task_id, entry in self._tasks:
        if task_filter and task_id != task_filter:
            continue

        # Run if: interval is due OR signalled
        due = self.is_due(task_id)
        signalled = task_id in signal_triggered

        if not due and not signalled:
            self._log.info(f"Skip {task_id} - not due, no signal")
            continue

        reason = "signalled" if signalled and not due else "due"
        self._log.info(f"Dispatching {task_id} ({entry.description}) [{reason}]")
        # ... rest of dispatch logic unchanged

    # Consume processed signals AFTER all dispatches in this cycle
    consumer = SignalConsumer(_SIGNALS_DIR)
    for task_id in signal_triggered:
        entry = self._get_task_entry(task_id)
        triggers = getattr(entry, "signal_triggers", []) or []
        for signal_type in triggers:
            consumed = consumer.consume_all(signal_type)
            if consumed:
                self._log.info(
                    f"Consumed {len(consumed)} '{signal_type}' signal(s) for {task_id}"
                )
```

Note: signals consumed AFTER dispatch to prevent signal-triggered re-dispatch in the same cycle if the agent runs fast enough to emit more signals.

---

## Agent Integration: Vision Agent Emits Signal

In `vision/tools/classify_images.py`, after successfully classifying and writing a batch:

```python
from shared.signal_bus import SignalEmitter

emitter = SignalEmitter(_SIGNALS_DIR)
for classified_path in successfully_classified:
    emitter.emit(
        signal_type="image-classified",
        emitter="vision-agent",
        ref=str(classified_path.name),
    )
```

`_SIGNALS_DIR` passed via `VaultConfig` or resolved from `PROJECT_ROOT`.

---

## `TaskDispatchEntry` Model Extension

In `shared/models.py` (or wherever `TaskDispatchEntry` is defined):

```python
class TaskDispatchEntry(BaseModel):
    intervalSeconds: int
    description: str
    dispatch: AgentDispatchConfig
    signal_triggers: list[str] = []  # NEW - signal types that trigger immediate dispatch
    emits_signals:   list[str] = []  # NEW - documentation only
```

Both fields are optional with empty-list defaults. No existing `agent.json` breaks.

---

## Signal Accumulation Safety

If the Vision Agent runs hourly but Lore Agent fails every run, signal files accumulate. After 24 hours: 24 signal files. This is harmless - signal files are tiny JSON. But add to cleanup scope:

In `cleanup/tools/cleanup_agent.py`:
```python
# Delete signal files older than 7 days
def purge_stale_signals(signals_dir: Path, max_age_days: int = 7) -> int:
    ...
```

---

## Tests

`agents/tests/test_signal_bus.py`:

```python
def test_emit_creates_signal_file(tmp_path):
    emitter = SignalEmitter(tmp_path / "signals")
    sid = emitter.emit("image-classified", "vision-agent", ref="test.png")
    assert (tmp_path / "signals" / f"{sid}.signal.json").exists()

def test_pending_returns_matching_signals(tmp_path):
    # Emit 2 "image-classified" and 1 "npc-generated"
    # consumer.pending("image-classified") should return 2

def test_consume_deletes_signal(tmp_path):
    emitter = SignalEmitter(tmp_path / "signals")
    consumer = SignalConsumer(tmp_path / "signals")
    sid = emitter.emit("test", "agent-a")
    consumer.consume(sid)
    assert not (tmp_path / "signals" / f"{sid}.signal.json").exists()

def test_corrupted_signal_discarded(tmp_path):
    p = tmp_path / "signals" / "bad.signal.json"
    p.parent.mkdir()
    p.write_text("{not valid json", encoding="utf-8")
    consumer = SignalConsumer(tmp_path / "signals")
    result = consumer.pending()
    assert result == []
    assert not p.exists()  # bad file deleted

def test_payload_too_large_raises(tmp_path):
    emitter = SignalEmitter(tmp_path / "signals")
    big = {"data": "x" * 2000}
    with pytest.raises(ValueError, match="too large"):
        emitter.emit("test", "agent", payload=big)

def test_signal_triggers_immediate_dispatch(tmp_path, monkeypatch):
    # Setup: lore-agent has signal_triggers=["image-classified"]
    # Lore is not due (ran 5 minutes ago)
    # Emit image-classified signal
    # Run _check_signals()
    # Assert: "lore-agent" in triggered set
```

---

## Success Criteria

- Vision Agent emits `image-classified` signal after each successful batch.
- Lore Agent dispatches within one runner cycle (≤60s) of signal emission, not 1 hour later.
- Signal files are deleted after consumption.
- Corrupted signal files are silently discarded.
- Signal accumulation (failed Lore) does not cause errors - signals pile up, await next successful run.
- No agent.json breaks (new fields are optional with empty defaults).
- Cleanup agent purges stale signals (> 7 days old).
