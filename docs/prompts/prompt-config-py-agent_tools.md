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

# shared\agent_tools.py
"""shared.agent_tools — self-management tools available to every agent.

Every agent's call_tool() dispatcher should delegate to call_self_management_tool()
before handling domain-specific tools.

Tool module contract (each agent tool file must expose):
    TOOLS: list[dict]                                 # Anthropic tool definitions
    call_tool(name, args, context) -> str             # dispatcher
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------

SELF_MANAGEMENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "write_log",
        "description": (
            "Append a structured log entry to this agent's daily log and the master "
            "automation.log. Use after each significant action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level":   {"type": "string", "enum": ["INFO", "WARN", "ERROR"], "description": "Log level"},
                "message": {"type": "string", "description": "Log message"},
            },
            "required": ["level", "message"],
        },
    },
    {
        "name": "read_state",
        "description": "Read a JSON state file by path relative to the project root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "State file path relative to project root"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_state",
        "description": "Atomically write or merge data into a JSON state file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":  {"type": "string", "description": "State file path relative to project root"},
                "data":  {"type": "object", "description": "Data to write (replaces file content)"},
                "merge": {"type": "boolean", "description": "If true, merge with existing content instead of replacing", "default": False},
            },
            "required": ["path", "data"],
        },
    },
    {
        "name": "request_human_review",
        "description": (
            "Flag a file or item for human attention. Writes an entry to "
            ".shared/state/review-requests.json. Use when something needs human judgment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item":   {"type": "string", "description": "File path or item identifier requiring review"},
                "reason": {"type": "string", "description": "Why human review is needed"},
            },
            "required": ["item", "reason"],
        },
    },
    {
        "name": "git_commit",
        "description": (
            "Stage the agent's declared commit_scope paths and create a git commit. "
            "Only call after all file changes are complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message (will be prefixed with 'chore(auto): ')"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "update_tool",
        "description": (
            "Rewrite an existing Python function in this agent's tools file. "
            "The new code replaces the named function. "
            "Use when a tool needs to be improved based on runtime experience."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string", "description": "Name of the function to replace"},
                "new_code":      {"type": "string", "description": "Complete new function definition (def ...: ...)"},
            },
            "required": ["function_name", "new_code"],
        },
    },
    {
        "name": "create_tool",
        "description": (
            "Add a new tool function to this agent's tools file and register it in TOOLS. "
            "The tool becomes available in future runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name":     {"type": "string", "description": "Snake-case name for the new tool"},
                "description":   {"type": "string", "description": "What the tool does (used in TOOLS list)"},
                "input_schema":  {"type": "object", "description": "JSON Schema for the tool's input parameters"},
                "function_code": {"type": "string", "description": "Complete function definition (def tool_name(args, context): ...)"},
            },
            "required": ["tool_name", "description", "input_schema", "function_code"],
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def call_self_management_tool(
    name: str,
    args: dict,
    context: dict,
    *,
    module_file: Optional[Path] = None,
    task_id: str = "agent",
) -> Optional[str]:
    """Handle a self-management tool call.

    Returns a result string if the tool was handled, None if the name is
    not a self-management tool (caller should then try domain tools).
    """
    if name == "write_log":
        return _write_log(args["level"], args["message"], context, task_id)
    if name == "read_state":
        return _read_state(args["path"], context)
    if name == "write_state":
        return _write_state(args["path"], args["data"], args.get("merge", False), context)
    if name == "request_human_review":
        return _request_human_review(args["item"], args["reason"], context, task_id)
    if name == "git_commit":
        return _git_commit(args["message"], context, task_id)
    if name == "update_tool":
        return _update_tool(args["function_name"], args["new_code"], module_file)
    if name == "create_tool":
        return _create_tool(
            args["tool_name"], args["description"],
            args["input_schema"], args["function_code"],
            module_file,
        )
    return None


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _agents_dir(context: dict) -> Path:
    return Path(context["project_root"]) / ".agents"


def _write_log(level: str, message: str, context: dict, task_id: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{task_id}] {level}: {message}\n"

    # Use master_log from context if provided (set by runner), else derive
    if context.get("master_log"):
        master = Path(context["master_log"])
    else:
        agents = _agents_dir(context)
        for candidate in ("runtime",):
            p = agents / candidate / "state" / "logs" / "automation.log"
            if p.parent.exists():
                master = p
                break
        else:
            master = agents / "runtime" / "state" / "logs" / "automation.log"

    master.parent.mkdir(parents=True, exist_ok=True)
    with open(master, "a", encoding="utf-8") as fh:
        fh.write(line)

    return f"Logged: {line.strip()}"


def _read_state(rel_path: str, context: dict) -> str:
    p = Path(context["project_root"]) / rel_path
    if not p.exists():
        return json.dumps({"error": f"File not found: {rel_path}"})
    try:
        return p.read_text(encoding="utf-8")
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _write_state(rel_path: str, data: dict, merge: bool, context: dict) -> str:
    p = Path(context["project_root"]) / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    if merge and p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
            existing.update(data)
            data = existing
        except Exception:
            pass
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)
    return f"Written: {rel_path}"


def _request_human_review(item: str, reason: str, context: dict, task_id: str) -> str:
    review_file = Path(context["project_root"]) / ".shared" / "state" / "review-requests.json"
    review_file.parent.mkdir(parents=True, exist_ok=True)

    requests: list[dict] = []
    if review_file.exists():
        try:
            requests = json.loads(review_file.read_text(encoding="utf-8"))
        except Exception:
            requests = []

    requests.append({
        "item":       item,
        "reason":     reason,
        "requestedAt": datetime.now(timezone.utc).isoformat(),
        "requestedBy": task_id,
        "resolved":   False,
    })

    tmp = review_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(requests, indent=2), encoding="utf-8")
    tmp.replace(review_file)
    return f"Review requested for: {item}"


def _git_commit(message: str, context: dict, task_id: str) -> str:
    project_root = context["project_root"]
    full_msg = f"chore(auto): {message}"
    try:
        result = subprocess.run(
            ["git", "commit", "-m", full_msg],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Committed: {full_msg}"
        return f"Commit skipped (nothing staged or error): {result.stderr.strip()}"
    except Exception as exc:
        return f"Commit failed: {exc}"


def _update_tool(function_name: str, new_code: str, module_file: Optional[Path]) -> str:
    if module_file is None:
        return "ERROR: module_file not provided — cannot locate tools file"

    try:
        ast.parse(new_code)
    except SyntaxError as exc:
        return f"ERROR: Syntax error in new_code: {exc}"

    source = module_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # find the function's start/end line
    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                func_node = node
                break

    if func_node is None:
        return f"ERROR: Function '{function_name}' not found in {module_file.name}"

    lines = source.splitlines(keepends=True)
    # find decorator start
    start = (func_node.decorator_list[0].lineno - 1) if func_node.decorator_list else (func_node.lineno - 1)
    end = func_node.end_lineno  # 1-based inclusive

    # detect indentation of the original function
    indent = len(lines[start]) - len(lines[start].lstrip())
    indented = textwrap.indent(textwrap.dedent(new_code), " " * indent)
    if not indented.endswith("\n"):
        indented += "\n"

    new_lines = lines[:start] + [indented] + lines[end:]
    module_file.write_text("".join(new_lines), encoding="utf-8")
    return f"Updated function '{function_name}' in {module_file.name}"


def _create_tool(
    tool_name: str,
    description: str,
    input_schema: dict,
    function_code: str,
    module_file: Optional[Path],
) -> str:
    if module_file is None:
        return "ERROR: module_file not provided — cannot locate tools file"

    try:
        ast.parse(function_code)
    except SyntaxError as exc:
        return f"ERROR: Syntax error in function_code: {exc}"

    source = module_file.read_text(encoding="utf-8")

    # Check TOOLS list exists
    if "TOOLS" not in source:
        return f"ERROR: No TOOLS list found in {module_file.name}"

    # Check for duplicate
    if f'"name": "{tool_name}"' in source or f"\"name\": \"{tool_name}\"" in source:
        return f"ERROR: Tool '{tool_name}' already exists"

    # Build the new tool entry string to splice into TOOLS
    tool_entry = json.dumps(
        {"name": tool_name, "description": description, "input_schema": input_schema},
        indent=4,
    )

    # Find the closing bracket of TOOLS list and insert before it
    # Locate `]\n` that closes TOOLS = [...] — find by scanning after "TOOLS = ["
    tools_start = source.find("TOOLS = [")
    if tools_start == -1:
        tools_start = source.find("TOOLS: list")
    if tools_start == -1:
        return f"ERROR: Could not locate TOOLS list in {module_file.name}"

    # Find the matching closing bracket
    depth = 0
    insert_pos = None
    for i in range(tools_start, len(source)):
        if source[i] == "[":
            depth += 1
        elif source[i] == "]":
            depth -= 1
            if depth == 0:
                insert_pos = i
                break

    if insert_pos is None:
        return "ERROR: Could not find end of TOOLS list"

    # Insert the new tool entry before the closing bracket
    tool_str = f"\n    {tool_entry},\n"
    new_source = source[:insert_pos] + tool_str + source[insert_pos:]

    # Append the function code at the end of file
    if not new_source.endswith("\n"):
        new_source += "\n"
    new_source += f"\n\n{textwrap.dedent(function_code)}\n"

    module_file.write_text(new_source, encoding="utf-8")
    return f"Created tool '{tool_name}' in {module_file.name}"


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

