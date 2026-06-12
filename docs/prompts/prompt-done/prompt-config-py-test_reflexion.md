You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.shared/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.shared/config/<script_name>.json`)
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
   - Do not include code — only configuration.

---

**Script to analyze:**

# tests\test_reflexion.py
"""Tests for the Lore Agent reflexion loop (impl-guide/01-reflexion-loop.md)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lore.tools.generate_npcs import _MAX_REVISIONS, _score_and_revise
from shared.models import NPCLLMOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_npc(**kwargs) -> NPCLLMOutput:
    defaults = {"name": "Test NPC", "ancestry": "human", "level": 1}
    defaults.update(kwargs)
    return NPCLLMOutput(**defaults)


def _make_gen(revisions: list[NPCLLMOutput] | None = None) -> MagicMock:
    gen = MagicMock()
    if revisions is not None:
        gen.generate_with_critique.side_effect = revisions
    else:
        gen.generate_with_critique.return_value = _make_npc()
    return gen


_SCENARIO = {"id": "s1", "arc": "A1"}
_IMAGE    = Path("fake.png")
_CTX     = ""
_IMG_REL = "images/fake.png"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_passes_on_first_try_if_score_7(monkeypatch) -> None:
    """Generator called exactly once (initial), no revision rounds."""
    import lore.tools.generate_npcs as mod
    monkeypatch.setattr(mod._GATE, "score", lambda _fm, _body: 7)

    gen    = _make_gen()
    result = _score_and_revise(gen, _IMAGE, _SCENARIO, _CTX, _make_npc(), _IMG_REL)

    assert result.needs_human_review is False
    gen.generate_with_critique.assert_not_called()


def test_revises_once_on_low_then_high_score(monkeypatch) -> None:
    """Score 4 → revision → score 8: generator called once, output not flagged."""
    import lore.tools.generate_npcs as mod

    revised = _make_npc(description="Improved description")
    scores  = iter([4, 8])
    monkeypatch.setattr(mod._GATE, "score", lambda _fm, _body: next(scores))

    gen    = _make_gen([revised])
    result = _score_and_revise(gen, _IMAGE, _SCENARIO, _CTX, _make_npc(), _IMG_REL)

    assert result.needs_human_review is False
    assert gen.generate_with_critique.call_count == 1


def test_flags_after_two_failed_rounds(monkeypatch) -> None:
    """Two revision rounds, both score < 7: output flagged, exactly 2 calls."""
    import lore.tools.generate_npcs as mod
    monkeypatch.setattr(mod._GATE, "score", lambda _fm, _body: 4)

    gen    = _make_gen([_make_npc(), _make_npc()])
    result = _score_and_revise(gen, _IMAGE, _SCENARIO, _CTX, _make_npc(), _IMG_REL)

    assert result.needs_human_review is True
    assert gen.generate_with_critique.call_count == _MAX_REVISIONS


def test_keeps_best_score_if_revision_regresses(monkeypatch) -> None:
    """Round 1 → 6, round 2 → 3 (regression): keep round-1 output, flag it."""
    import lore.tools.generate_npcs as mod

    round1 = _make_npc(description="Round 1 output")
    round2 = _make_npc(description="Round 2 output — worse")
    scores = iter([4, 6, 3])
    monkeypatch.setattr(mod._GATE, "score", lambda _fm, _body: next(scores))

    gen    = _make_gen([round1, round2])
    result = _score_and_revise(gen, _IMAGE, _SCENARIO, _CTX, _make_npc(), _IMG_REL)

    assert result.needs_human_review is True
    assert result.description == "Round 1 output"
    assert gen.generate_with_critique.call_count == 2


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .shared/config/
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

