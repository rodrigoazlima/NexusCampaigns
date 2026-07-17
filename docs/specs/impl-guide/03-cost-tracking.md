# Impl: Cost Tracking - Claude API Runner

**Phase:** P1  
**Priority:** High  
**Effort:** 1 day  
**Depends on:** nothing (modifies existing runner)

---

## Problem

Claude API calls emit token usage in every response body under `usage.input_tokens` and `usage.output_tokens`. The current runner (`shared/runners/claude.py`) discards this data. Agents run hourly with `max_tokens: 4096` and `max_tool_rounds: 20`. No budget guard exists. One stuck agent in a retry loop, or an agent processing a large inbox batch, can incur unbounded API costs silently.

This also blocks implementation of the semantic quality judge (P5), which requires per-task cost awareness before it can be enabled.

---

## Goal

1. The Claude runner records token usage per run into a structured cost log.
2. The orchestrator exposes cumulative daily cost per task.
3. `agent.json` supports an optional `max_tokens_per_run` guard that aborts the run if exceeded.
4. The daily review report includes a cost summary section.

---

## Scope

Files to modify:
- `agents/shared/runners/claude.py` - capture `usage` fields from API response
- `agents/runtime/tools/runner.py` - record cost after each dispatch
- `agents/review/tools/daily_report.py` - add cost summary to report

Files to create:
- `agents/runtime/state/costs/` - directory, one JSON per day
- `agents/tests/test_cost_tracking.py`

---

## Token Cost Model

Pricing as of 2026-06 (verify against Anthropic pricing page before enabling budget guards):

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|-----------------------|------------------------|
| claude-haiku-4-5 | $0.80 | $4.00 |
| claude-sonnet-4-6 | $3.00 | $15.00 |
| claude-opus-4-8 | $15.00 | $75.00 |

Store raw token counts, not dollar amounts - pricing changes. Compute cost on read.

---

## Claude Runner Changes (`shared/runners/claude.py`)

### Current RunResult

```python
@dataclass
class RunResult:
    exit_code: int
    error: Optional[str] = None
    output: Optional[str] = None
```

### Extended RunResult

Add token usage fields:

```python
@dataclass
class RunResult:
    exit_code: int
    error: Optional[str] = None
    output: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
```

### Capture in runner

After each API response in the Claude runner's tool-use loop, accumulate tokens:

```python
total_input = 0
total_output = 0

for round_num in range(max_tool_rounds):
    response = _call_claude_api(...)
    usage = response.get("usage", {})
    total_input  += usage.get("input_tokens", 0)
    total_output += usage.get("output_tokens", 0)
    # ... existing tool dispatch logic

result.input_tokens = total_input
result.output_tokens = total_output
result.model = model_id
```

This is additive across all rounds of a single run - total cost of one agent execution.

---

## Orchestrator Changes (`runtime/tools/runner.py`)

### Cost recording after dispatch

After `exit_code = self.dispatch(task_id)`, call `_record_cost(...)`:

```python
def _record_cost(
    task_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    started_at: datetime,
) -> None:
    today = started_at.strftime("%Y-%m-%d")
    cost_dir = _RUNTIME_STATE / "costs"
    cost_dir.mkdir(parents=True, exist_ok=True)
    cost_file = cost_dir / f"costs-{today}.json"

    data: dict = {}
    if cost_file.exists():
        try:
            data = json.loads(cost_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    entry = data.setdefault(task_id, {"runs": []})
    entry["runs"].append({
        "ts":            started_at.isoformat(),
        "model":         model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
    })

    tmp = cost_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(cost_file)
```

The RunResult must propagate from `dispatch()` back to `run_cycle()`. Currently `dispatch()` returns only `int` (exit code). This requires adding a return type change:

```python
# Before:
def dispatch(self, task_id: str) -> int:

# After:
def dispatch(self, task_id: str) -> tuple[int, RunResult]:
```

Update `IOrchestrator` interface accordingly.

---

## Optional Budget Guard

Add to `agent.json` dispatch config (all dispatch types, optional):

```json
{
  "claude_api": {
    "model": "claude-sonnet-4-6",
    "max_tokens_per_run": 50000,
    ...
  }
}
```

In `AgentDispatchConfig` model (add optional field):

```python
class ClaudeApiConfig(BaseModel):
    model: str
    system_file: str
    tools_module: str
    history_file: str
    max_tokens: int = 4096
    timeout_seconds: int = 600
    max_tool_rounds: int = 20
    max_tokens_per_run: Optional[int] = None  # NEW: abort if exceeded
```

In the Claude runner, check after each round:

```python
if cfg.max_tokens_per_run and (total_input + total_output) > cfg.max_tokens_per_run:
    log.warning(f"Token budget exceeded ({total_input + total_output} > {cfg.max_tokens_per_run}). Stopping.")
    break
```

---

## Cost File Format

`agents/runtime/state/costs/costs-2026-06-10.json`:

```json
{
  "lore-agent": {
    "runs": [
      {
        "ts": "2026-06-10T08:00:01Z",
        "model": "claude-sonnet-4-6",
        "input_tokens": 12450,
        "output_tokens": 3200
      }
    ]
  },
  "vision-agent": {
    "runs": [
      {
        "ts": "2026-06-10T08:01:00Z",
        "model": "claude-sonnet-4-6",
        "input_tokens": 8300,
        "output_tokens": 1100
      }
    ]
  }
}
```

One file per calendar day. Rotated by cleanup agent (add `costs/` to cleanup scope).

---

## Daily Report Addition (`review/tools/daily_report.py`)

Add `cost_summary` field to `DailyReport` model:

```python
@dataclass
class CostSummary:
    date: str
    by_task: dict[str, TaskCostEntry]
    total_input_tokens: int
    total_output_tokens: int

@dataclass
class TaskCostEntry:
    task_id: str
    model: str
    runs: int
    input_tokens: int
    output_tokens: int
```

Report displays per-task token totals for the day. Dollar amounts computed client-side (report HTML/JS) using current pricing constants, not stored in JSON.

---

## Tests

`agents/tests/test_cost_tracking.py`:

```python
def test_run_result_captures_tokens():
    # Mock Claude API response with usage={input_tokens:100, output_tokens:50}
    # Run runner
    # Assert RunResult.input_tokens == 100, output_tokens == 50

def test_multi_round_tokens_accumulate():
    # Mock 3 rounds with 100 tokens each
    # Assert RunResult.input_tokens == 300

def test_cost_file_written_after_dispatch(tmp_path):
    # Run one dispatch cycle
    # Assert costs-{today}.json created with correct structure

def test_budget_guard_stops_runner(tmp_path):
    # Set max_tokens_per_run = 100
    # Mock: round 1 = 80 tokens, round 2 = 80 tokens
    # Assert: stops after round 1 (would exceed on round 2)

def test_cost_file_atomic_write(tmp_path):
    # Simulate interrupted write (check .tmp is cleaned up)
    # Assert no partial cost file left
```

---

## Success Criteria

- Every Claude API run records `input_tokens`, `output_tokens`, `model` to `costs-{date}.json`.
- Token totals accumulate correctly across all tool-use rounds in a single run.
- Daily report includes cost summary section.
- `max_tokens_per_run` guard, when set, halts the runner mid-run without error.
- Cleanup agent rotates cost files (add to cleanup scope in P2).
- No existing agent.json breaks due to new optional fields.
