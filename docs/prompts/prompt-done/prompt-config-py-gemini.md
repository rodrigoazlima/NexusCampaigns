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

# shared\runners\gemini.py
"""GeminiRunner - Google Gemini API.

Dispatch config keys (from GeminiApiConfig):
  model            str   - model ID, e.g. gemini-2.5-flash
  system_file      str?  - path to system prompt, relative to agent_dir
  prompt_file      str?  - path to user prompt, relative to agent_dir
  max_tokens       int   - default 2048
  temperature      float - default 0.0
  timeout_seconds  int   - default 120 (accepted; SDK timeout via request_options)

Auth: GEMINI_API_KEY env var.

Requires: pip install google-generativeai
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..models import RunResult
from . import _resolve_placeholders

_MAX_RETRIES   = 3
_RETRY_DELAY_S = 3.0


class GeminiRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError:
            return RunResult(
                exit_code=1,
                error="google-generativeai package not installed - run: pip install google-generativeai",
            )

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return RunResult(exit_code=1, error="GEMINI_API_KEY env var not set")

        cfg         = dispatch_config
        model_name  = cfg["model"]
        max_tokens  = int(cfg.get("max_tokens", 2048))
        temperature = float(cfg.get("temperature", 0.0))
        agent_dir   = Path(context["agent_dir"])

        # ------------------------------------------------------------------ #
        # Load prompts
        # ------------------------------------------------------------------ #
        system = _load_file(agent_dir, cfg.get("system_file"), context)
        prompt = _load_file(agent_dir, cfg.get("prompt_file"), context)

        # ------------------------------------------------------------------ #
        # SDK call with retries
        # ------------------------------------------------------------------ #
        t0         = time.monotonic()
        last_error: str | None = None

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system or None,
            )
            gen_config = genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            return RunResult(exit_code=1, error=f"Gemini init error: {exc}", duration_ms=_ms(t0))

        for attempt in range(_MAX_RETRIES):
            try:
                response = model.generate_content(prompt, generation_config=gen_config)
                text = response.text
                return RunResult(exit_code=0, output=text, duration_ms=_ms(t0))

            except Exception as exc:
                last_error = f"Gemini API error (attempt {attempt + 1}): {exc}"

            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_S)

        return RunResult(exit_code=1, error=last_error, duration_ms=_ms(t0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_file(agent_dir: Path, filename: str | None, context: dict) -> str:
    if not filename:
        return ""
    p = agent_dir / filename
    if not p.exists():
        return ""
    return _resolve_placeholders(p.read_text(encoding="utf-8").strip(), context)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


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

