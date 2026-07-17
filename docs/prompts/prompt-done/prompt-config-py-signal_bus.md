You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.system/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.system/config/<script_name>.json`)
     - Contains script-specific settings and overrides.
     - Always loaded after global config (can override global values).
     - Can be empty (`{}`) but must always exist.

2. **Output Format:**
   - You must output **two valid JSON objects** clearly labeled.
   - Use sensible, descriptive keys in `snake_case`.
   - Include meaningful `default` values for every setting.
   - Add a `"description"` field for each major setting when helpful.
   - Group related settings under logical sections if needed.

3. **What to Extract:**
   - Hardcoded paths (especially those derived from `__file__`)
   - Constants (BATCH_SIZE, thresholds, limits, etc.)
   - LLM settings (URL, model, provider, etc.)
   - File/directory references
   - Magic numbers and strings that are likely to change
   - Any environment-dependent behavior

4. **Rules:**
   - Prefer putting common things (project roots, LLM config, logging, shared directories) in **global**.
   - Put script-specific behavior (batch sizes, task-specific prompts, agent name, etc.) in **local**.
   - Make sure the JSONs contain good defaults so the script works even if the files are deleted.
   - Use clear, consistent naming.
   - Do not include code - only configuration.

---

**Script to analyze:**

# shared\signal_bus.py
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


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .system/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```

### Bonus: Loader Code Suggestion (for `shared/config.py`)

You can later create a simple loader like this:

```python
from pathlib import Path
import json

def load_config(script_path: Path):
    project_root = Path(__file__).resolve().parents[2]  # adjust as needed
    
    # Global
    global_path = project_root / "config" / "global.json"
    global_cfg = json.loads(global_path.read_text()) if global_path.exists() else {}
    
    # Local
    script_name = script_path.stem
    local_path = project_root / "config" / f"{script_name}.json"
    local_cfg = json.loads(local_path.read_text()) if local_path.exists() else {}
    
    # Merge (local overrides global)
    config = {**global_cfg, **local_cfg}
    return config
```

