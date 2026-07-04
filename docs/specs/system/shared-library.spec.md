# Spec — Shared Python Library

Location: `agents/shared/`

Shared code used by 3+ agents. Agent-specific logic stays in `{agent}/tools/`. Code moves to `system/` only when reuse threshold is met.

---

## Module Index

| Module | Purpose |
|--------|---------|
| `interfaces.py` | All abstract interfaces and protocols for pipeline components |
| `models.py` | Pydantic data models for all state files, LLM outputs, and reports |
| `config.py` | `VaultConfig`, `VaultPaths`, `SystemPaths`, `LLMEndpointConfig` dataclasses |
| `loaders.py` | `load_vault_config()` — reads `registry.yaml`, constructs `VaultConfig` |
| `defaults.py` | Default empty structures for all state files (used by `IStateStore.init_defaults()`) |
| `agent_tools.py` | Tool definitions for Claude tool-use dispatch agents |
| `llm_client.py` | `ILLMClient` implementation — HTTP calls with retry and vision support |
| `logger.py` | `ILogger` implementation — dual-file logging (shared log + per-agent daily rotation) |
| `frontmatter_io.py` | `IFrontmatterIO` implementation — ruamel.yaml read/write for entity files |
| `state_store.py` | `IStateStore` implementation — atomic JSON read/write with file locking |
| `quality_gate.py` | `IQualityGate` implementation — quality score computation (0–10) |
| `vault_guard.py` | `IVaultGuard` implementation — write-protection enforcement |
| `entity_scanner.py` | Scan vault directories and return parsed `EntityFrontmatter` objects |
| `slug_utils.py` | Slug generation, normalization, collision resolution |

### runners/

| Module | Runner class | Dispatch type |
|--------|-------------|---------------|
| `runners/__init__.py` | `get_runner()` factory + `IRunner` protocol | — |
| `runners/cli.py` | `CliRunner` | `cli` |
| `runners/openai_compat.py` | `OpenAICompatRunner` | `openai-api` |
| `runners/claude.py` | `ClaudeRunner` | `claude-api` |
| `runners/gemini.py` | `GeminiRunner` | `gemini-api` |
| `runners/openrouter.py` | `OpenRouterRunner` | `openrouter-api` |

---

## Key Interfaces (`interfaces.py`)

### `IAgent`

```python
class IAgent(Protocol):
    TASK_ID:         str
    SCRIPT_BASENAME: str
    BATCH_SIZE:      int

    def execute(self) -> int: ...
    def run_batch(self) -> tuple[int, int]: ...
```

All pipeline agents satisfy this protocol. `execute()` returns 0 on success, 1 on failure.

### `BaseAgent`

Abstract base class. Enforces `TASK_ID`, `SCRIPT_BASENAME`, `BATCH_SIZE`. Provides default `execute()` that calls `bootstrap()` → `run_batch()` and emits `--- START ---` / `--- DONE ---` log lines.

### `IStateStore`

```python
class IStateStore(ABC):
    def load(self) -> Any: ...
    def save(self, data: Any) -> None: ...       # atomic (tmp-rename pattern)
    def update(self, updater) -> None: ...       # lock → load → apply → save
    def init_defaults(self) -> None: ...         # idempotent bootstrap
```

### `IVaultGuard`

```python
class IVaultGuard(ABC):
    def assert_writable(self, target: Path) -> None: ...          # raises VaultWriteError
    def assert_not_inbox_delete(self, target: Path) -> None: ...  # raises PermissionError
```

Protected dirs: `02-Library/`, `00-Inbox/`.

### `IQualityGate`

Scoring formula (0–10, +2 each):
- description section present
- relationships with `[[links]]`
- ≥3 tags
- `type` field set
- `source` field set

```python
class IQualityGate(ABC):
    def score(self, frontmatter: dict, body: str) -> int: ...
    def is_library_ready(self, frontmatter: dict) -> bool: ...   # quality ≥ 7, reviewed=True, relationships non-empty
```

---

## Exceptions

| Exception | Meaning |
|-----------|---------|
| `LLMOfflineError` | LLM server unreachable — skip batch, retry next run |
| `LLMResponseError` | LLM returned unexpected content after all retries |
| `VaultWriteError` | Attempted write to a protected vault directory |
| `DispatchError` | Orchestrator could not dispatch an agent |

---

## Paths

System paths are derived from a single `project_root` via `SystemPaths`:

| Property | Resolved path |
|----------|--------------|
| `agents_dir` | `{project_root}/agents/` |
| `shared_state` | `{project_root}/system/state/` |
| `logs_dir` | `{project_root}/agents/runtime/state/logs/` |
| `reports_dir` | `{project_root}/agents/review/state/reports/` |
| `agent_state(name)` | `{project_root}/agents/{name}/state/` |
