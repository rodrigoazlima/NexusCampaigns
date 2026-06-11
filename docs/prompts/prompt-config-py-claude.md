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

# shared\runners\claude.py
"""ClaudeRunner — Anthropic Claude API with agentic tool-calling loop.

Dispatch config keys (from ClaudeApiConfig):
  model            str   — Claude model ID
  system_file      str?  — path to system prompt, relative to agent_dir
  tools_module     str?  — dotted import path for agent's tool module
  history_file     str?  — filename for persistent chat history, under agent state/
  max_tokens       int   — default 4096
  timeout_seconds  int   — default 120 (per API call)
  max_tool_rounds  int   — agentic loop cap, default 20

The tools module must expose:
  TOOLS: list[dict]                        — Anthropic tool definitions
  call_tool(name, args, context) -> str    — tool dispatcher
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

from ..models import RunResult


class ClaudeRunner:
    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        try:
            import anthropic
        except ImportError:
            return RunResult(
                exit_code=1,
                error="anthropic package not installed — run: pip install anthropic",
            )

        cfg          = dispatch_config
        agent_dir    = Path(context["agent_dir"])
        project_root = Path(context["project_root"])
        agents_dir   = Path(context.get("agents_dir", str(agent_dir.parent)))

        # ------------------------------------------------------------------ #
        # Load tools module
        # ------------------------------------------------------------------ #
        mod = None
        tools: list[dict] = []
        if cfg.get("tools_module"):
            module_path = cfg["tools_module"]
            # Ensure .agents/ is on sys.path
            if str(agents_dir) not in sys.path:
                sys.path.insert(0, str(agents_dir))
            try:
                mod = importlib.import_module(module_path)
                tools = list(getattr(mod, "TOOLS", []))
            except Exception as exc:
                return RunResult(exit_code=1, error=f"Failed to import tools_module {module_path!r}: {exc}")

        # ------------------------------------------------------------------ #
        # System prompt
        # ------------------------------------------------------------------ #
        system = ""
        if cfg.get("system_file"):
            p = agent_dir / cfg["system_file"]
            if p.exists():
                system = p.read_text(encoding="utf-8").strip()

        # ------------------------------------------------------------------ #
        # Chat history (persistent across runs for multi-turn continuity)
        # ------------------------------------------------------------------ #
        history_path: Optional[Path] = None
        messages: list[dict] = []

        if cfg.get("history_file"):
            history_path = agent_dir / "state" / cfg["history_file"]
            history_path.parent.mkdir(parents=True, exist_ok=True)
            if history_path.exists():
                try:
                    messages = json.loads(history_path.read_text(encoding="utf-8"))
                except Exception:
                    messages = []

        # Add current task invocation
        messages.append({
            "role": "user",
            "content": (
                f"Execute your scheduled task now. "
                f"Project root: {project_root}. "
                f"Agent dir: {agent_dir}. "
                f"Use your tools to complete the task, then stop."
            ),
        })

        # ------------------------------------------------------------------ #
        # Agentic loop
        # ------------------------------------------------------------------ #
        client = anthropic.Anthropic()
        max_rounds      = int(cfg.get("max_tool_rounds", 20))
        max_tokens_run  = cfg.get("max_tokens_per_run")  # optional budget guard
        model_id        = cfg["model"]
        exit_code       = 0
        last_error: Optional[str] = None
        total_input     = 0
        total_output    = 0

        try:
            for round_num in range(max_rounds):
                create_kwargs: dict[str, Any] = {
                    "model":      model_id,
                    "messages":   messages,
                    "max_tokens": int(cfg.get("max_tokens", 4096)),
                }
                if system:
                    create_kwargs["system"] = system
                if tools:
                    create_kwargs["tools"] = tools

                resp = client.messages.create(**create_kwargs)

                # Accumulate token usage
                if hasattr(resp, "usage") and resp.usage:
                    total_input  += getattr(resp.usage, "input_tokens", 0)
                    total_output += getattr(resp.usage, "output_tokens", 0)

                # Convert content blocks to serialisable form for history
                assistant_content = _serialise_content(resp.content)
                messages.append({"role": "assistant", "content": assistant_content})

                if resp.stop_reason == "end_turn":
                    break

                if resp.stop_reason != "tool_use":
                    break

                # Budget guard — check after accumulating tokens
                if max_tokens_run and (total_input + total_output) > max_tokens_run:
                    last_error = (
                        f"Token budget exceeded "
                        f"({total_input + total_output} > {max_tokens_run}). Stopping."
                    )
                    break

                # Execute all tool calls in this response
                tool_results: list[dict] = []
                for blk in resp.content:
                    if blk.type != "tool_use":
                        continue
                    try:
                        result = mod.call_tool(blk.name, blk.input, context)
                    except Exception as exc:
                        result = f"ERROR: {exc}"
                        exit_code = 1
                        last_error = str(exc)

                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": blk.id,
                        "content":     str(result),
                    })

                messages.append({"role": "user", "content": tool_results})

            else:
                # Hit max_rounds without end_turn
                exit_code = 1
                last_error = f"Agent hit max_tool_rounds={max_rounds} without completing"

        except Exception as exc:
            exit_code = 1
            last_error = str(exc)

        finally:
            # Persist chat history — keep last 50 turns to bound file size
            if history_path is not None:
                _save_history(history_path, messages)

        return RunResult(
            exit_code=exit_code,
            error=last_error,
            input_tokens=total_input,
            output_tokens=total_output,
            model=model_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialise_content(content) -> list[dict]:
    """Convert SDK content blocks to plain dicts for JSON serialisation."""
    result = []
    for blk in content:
        if hasattr(blk, "model_dump"):
            result.append(blk.model_dump())
        elif hasattr(blk, "__dict__"):
            result.append({k: v for k, v in blk.__dict__.items() if not k.startswith("_")})
        else:
            result.append({"type": "unknown", "text": str(blk)})
    return result


def _save_history(path: Path, messages: list[dict]) -> None:
    """Persist chat history, trimmed to last 50 messages."""
    trimmed = messages[-50:]
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(trimmed, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


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

