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

# shared\interfaces.py
"""Abstract interfaces and base classes for all pipeline components.

Protocols (I*) define structural contracts - no implementation.
BaseAgent provides a concrete default execute() per shared-library.spec.md.
Concrete implementations live in each agent's tools/ package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from .config import VaultConfig
from .logger import Logger
from .models import (
    AgentDispatchConfig,
    AgentFolderConfig,
    AgentMetrics,
    CanonReport,
    CuratorSuggestion,
    DailyReport,
    DedupCandidate,
    EntityFrontmatter,
    InboxQueue,
    ProcessedImagesState,
    ProcessedNPCs,
    RegistryConfig,
    RelationshipGraph,
    RepairReport,
    ReviewItem,
    RunResult,
    SearchEntry,
    SearchIndexState,
    TagEnrichmentOutput,
    VisionClassification,
    NPCLLMOutput,
)


# ---------------------------------------------------------------------------
# IAgent - every pipeline agent satisfies this contract
# ---------------------------------------------------------------------------

@runtime_checkable
class IAgent(Protocol):
    """Structural protocol. All agents expose execute() → exit code."""

    TASK_ID:         str
    SCRIPT_BASENAME: str
    BATCH_SIZE:      int

    def execute(self) -> int:
        """Run the agent. Returns 0 on success, 1 on partial/total failure."""
        ...

    def run_batch(self) -> tuple[int, int]:
        """Process up to BATCH_SIZE items. Returns (count, failed)."""
        ...


class BaseAgent(ABC):
    """Abstract base class for all vault pipeline agents.

    Subclasses must define TASK_ID, SCRIPT_BASENAME and implement
    bootstrap() + run_batch(). execute() has a default implementation
    that handles the full agent lifecycle per shared-library.spec.md:
      bootstrap() → START log → run_batch() → DONE log → return exit code.

    Override DONE_KEY to customise the item-count label in the DONE line
    (data-contracts.spec.md: processed | classified | enriched | ...).
    """

    TASK_ID:         str
    SCRIPT_BASENAME: str
    BATCH_SIZE:      int = 10
    DONE_KEY:        str = "processed"

    def __init__(self, cfg: VaultConfig) -> None:
        self.cfg = cfg

    @abstractmethod
    def bootstrap(self) -> None:
        """Ensure all required state files and directories exist.
        Called once at startup before execute(). Must be idempotent.
        """
        ...

    @abstractmethod
    def run_batch(self) -> tuple[int, int]:
        """Process up to BATCH_SIZE items. Returns (count, failed)."""
        ...

    def execute(self) -> int:
        """Default agent lifecycle: bootstrap → START → run_batch → DONE.

        Creates a Logger from VaultConfig paths and TASK_ID / SCRIPT_BASENAME.
        Per-agent daily log: .agents/{name}/state/logs/{basename}_YYYY-MM-DD.log.
        Master log:          .agents/runtime/state/logs/automation.log.

        Returns 0 on success, 1 if any items failed or an exception was raised.
        Subclasses may override for custom lifecycle control.
        """
        agent_name = self.TASK_ID.removesuffix("-agent")
        logs_dir   = self.cfg.system_paths.agent_state(agent_name) / "logs"
        master_log = self.cfg.system_paths.logs_dir / "automation.log"
        logger = Logger(
            task_id        = self.TASK_ID,
            script_basename= self.SCRIPT_BASENAME,
            logs_dir       = logs_dir,
            master_log     = master_log,
        )
        self._logger = logger

        self.bootstrap()
        t0 = logger.start()
        try:
            count, failed = self.run_batch()
        except Exception as exc:
            logger.error(str(exc))
            logger.done(t0, key=self.DONE_KEY, count=0, failed=1)
            return 1
        logger.done(t0, key=self.DONE_KEY, count=count, failed=failed)
        return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# ILogger
# ---------------------------------------------------------------------------

@runtime_checkable
class ILogger(Protocol):
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
    def start(self) -> float: ...
    def done(self, t0: float, *, key: str, count: int, failed: int) -> None: ...


# ---------------------------------------------------------------------------
# ILLMClient
# ---------------------------------------------------------------------------

class ILLMClient(ABC):
    """Contract for LLM interaction. Temperature=0. Max 3 retries."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
    ) -> str:
        """Send messages, return raw content string.
        Raises LLMOfflineError on connection failure.
        Raises LLMResponseError after retries exhausted.
        """
        ...

    @abstractmethod
    def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Send messages, parse and return JSON response."""
        ...

    @abstractmethod
    def vision_chat(
        self,
        image_path: Path,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Encode image + prompt and return JSON response."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the LLM server is reachable."""
        ...


# ---------------------------------------------------------------------------
# IStateStore
# ---------------------------------------------------------------------------

class IStateStore(ABC):
    """Contract for reading/writing a single JSON state file atomically.

    State files are gitignored runtime artefacts. init_defaults() must be
    called on agent bootstrap to ensure the file exists before any read.
    """

    @abstractmethod
    def load(self) -> Any:
        """Read and return current state. Returns default if file absent."""
        ...

    @abstractmethod
    def save(self, data: Any) -> None:
        """Persist state atomically (tmp-rename pattern)."""
        ...

    @abstractmethod
    def update(self, updater) -> None:
        """Acquire lock → load → apply updater(data) → save → release."""
        ...

    @abstractmethod
    def init_defaults(self) -> None:
        """Write the default empty structure if the file does not yet exist.
        Idempotent - never overwrites an existing file.
        Default structures are defined in shared.defaults.
        """
        ...


# ---------------------------------------------------------------------------
# IFrontmatterIO
# ---------------------------------------------------------------------------

class IFrontmatterIO(ABC):
    """Contract for reading/writing YAML frontmatter in Markdown files."""

    @abstractmethod
    def read(self, path: Path) -> tuple[dict, str]:
        """Return (frontmatter_dict, body_str). Preserves comment order."""
        ...

    @abstractmethod
    def write(self, path: Path, frontmatter: dict, body: str) -> None:
        """Serialise frontmatter + body to path using ruamel.yaml."""
        ...


# ---------------------------------------------------------------------------
# IVaultGuard
# ---------------------------------------------------------------------------

class IVaultGuard(ABC):
    """Contract for security checks on vault write/delete operations."""

    @abstractmethod
    def assert_writable(self, target: Path) -> None:
        """Raise VaultWriteError if target is inside a write-protected dir.
        Protected dirs: 02-Library/, 00-Inbox/.
        """
        ...

    @abstractmethod
    def assert_not_inbox_delete(self, target: Path) -> None:
        """Raise VaultWriteError if target is inside 00-Inbox/."""
        ...

    @abstractmethod
    def assert_not_self_approved(self, frontmatter: dict) -> None:
        """Raise VaultWriteError if frontmatter contains human-only field values.

        Forbidden: status='approved', reviewed=True.
        These fields are set exclusively by humans. Agents must call this
        before any frontmatter write to enforce security.spec.md Rule G3.
        """
        ...


# ---------------------------------------------------------------------------
# IImageClassifier (vision agent contract)
# ---------------------------------------------------------------------------

class IImageClassifier(ABC):
    """Contract for the vision agent's LLM-based image classification."""

    @abstractmethod
    def classify(self, image_path: Path) -> VisionClassification:
        """Return classification for a single image.
        Raises LLMOfflineError if server unreachable.
        """
        ...

    @abstractmethod
    def is_token(self, image_path: Path) -> bool:
        """Return True if image is a circular portrait token (PNG alpha check)."""
        ...


# ---------------------------------------------------------------------------
# IFaceMatcher (vision agent token-matching contract)
# ---------------------------------------------------------------------------

class IFaceMatcher(ABC):
    """Contract for matching a token image to its source portrait."""

    @abstractmethod
    def find_best_match(
        self,
        token_path: Path,
        candidates: list[Path],
    ) -> Optional[Path]:
        """Return best-matching source portrait or None if below threshold."""
        ...


# ---------------------------------------------------------------------------
# INPCGenerator (lore agent contract)
# ---------------------------------------------------------------------------

class INPCGenerator(ABC):
    """Contract for generating NPC sheets from image × scenario pairs."""

    @abstractmethod
    def generate(
        self,
        image_path: Path,
        scenario: dict,
        canon_context: str,
    ) -> NPCLLMOutput:
        """Return a validated NPC output for the given image + scenario.
        Raises LLMOfflineError if server unreachable.
        """
        ...

    @abstractmethod
    def generate_with_critique(
        self,
        image_path: Path,
        scenario: dict,
        canon_context: str,
        critique: str,
    ) -> NPCLLMOutput:
        """Re-generate with critique injected into user turn. Same contract as generate()."""
        ...


# ---------------------------------------------------------------------------
# ITokenRenderer (token agent contract)
# ---------------------------------------------------------------------------

class ITokenRenderer(ABC):
    """Contract for producing circular portrait tokens."""

    @abstractmethod
    def render(
        self,
        source: Path,
        frame: Optional[Path],
        output: Path,
    ) -> None:
        """Crop → circle mask → composite frame → save PNG."""
        ...


# ---------------------------------------------------------------------------
# ITagEnricher (classification agent contract)
# ---------------------------------------------------------------------------

class ITagEnricher(ABC):
    """Contract for tag enrichment and type inference."""

    @abstractmethod
    def enrich(
        self,
        title: str,
        current_tags: list[str],
        content_excerpt: str,
    ) -> TagEnrichmentOutput:
        """Return new tags and inferred type. Never returns disallowed tags."""
        ...


# ---------------------------------------------------------------------------
# IWikiCompiler (wiki agent contract)
# ---------------------------------------------------------------------------

class IWikiCompiler(ABC):
    """Contract for synthesising entity pages from raw notes."""

    @abstractmethod
    def compile(self, raw_content: str) -> str:
        """Return a structured Obsidian-format Markdown page."""
        ...


# ---------------------------------------------------------------------------
# IReportBuilder (review agent contract)
# ---------------------------------------------------------------------------

class IReportBuilder(ABC):
    """Contract for assembling daily vault health reports."""

    @abstractmethod
    def build(self) -> DailyReport:
        """Aggregate log parse + vault health scan into a DailyReport."""
        ...


# ---------------------------------------------------------------------------
# IRunner - dispatch abstraction
# ---------------------------------------------------------------------------

@runtime_checkable
class IRunner(Protocol):
    """Structural protocol for all dispatch runners."""

    def run(self, dispatch_config: dict, context: dict) -> RunResult:
        """Execute agent via the runner's transport.

        dispatch_config - the type-specific sub-config dict (e.g. cli, openai_api).
        context - runtime values: {"project_root": str, "agent_dir": str}.
        Returns RunResult; never raises on transport errors (captures to .error).
        """
        ...


# ---------------------------------------------------------------------------
# IOrchestrator
# ---------------------------------------------------------------------------

class IOrchestrator(ABC):
    """Contract for the runner - schedules and dispatches agents."""

    @abstractmethod
    def is_due(self, task_id: str) -> bool:
        """Return True if elapsed ≥ intervalSeconds for this task."""
        ...

    @abstractmethod
    def load_agent_dispatch(self, task_id: str) -> Optional[AgentDispatchConfig]:
        """Load dispatch config for task_id from its agent.json. Returns None if absent."""
        ...

    @abstractmethod
    def dispatch(self, task_id: str) -> tuple[int, RunResult]:
        """Resolve agent.json, select runner, execute. Return (exit_code, RunResult)."""
        ...

    @abstractmethod
    def commit_changes(self, task_id: str) -> None:
        """Stage commit_scope paths and git commit after a successful agent run."""
        ...


# ---------------------------------------------------------------------------
# IQualityGate (shared quality scoring contract)
# ---------------------------------------------------------------------------

class IQualityGate(ABC):
    """Contract for computing and enforcing quality scores.

    Scoring formula (0–10, +2 each):
      description section present · relationships with [[links]] ·
      ≥3 tags · type field set · source field set.
    """

    @abstractmethod
    def score(self, frontmatter: dict, body: str) -> int:
        """Compute quality score 0–10. Pure - no I/O."""
        ...

    @abstractmethod
    def is_library_ready(self, frontmatter: dict) -> bool:
        """Return True if quality ≥ 7, reviewed=True, and relationships non-empty."""
        ...


# ---------------------------------------------------------------------------
# IWikilinkResolver (wikilink agent contract)
# ---------------------------------------------------------------------------

class IWikilinkResolver(ABC):
    """Contract for resolving and inserting [[wikilinks]] in vault files."""

    @abstractmethod
    def build_slug_index(self, library_dir: Path) -> dict[str, Path]:
        """Return {slug: path} for every .md in library_dir."""
        ...

    @abstractmethod
    def insert_wikilinks(
        self,
        target: Path,
        slug_index: dict[str, Path],
    ) -> int:
        """Insert missing [[slug]] into ## Related section. Return count inserted."""
        ...


# ---------------------------------------------------------------------------
# IRelationshipBuilder (relationship agent contract)
# ---------------------------------------------------------------------------

class IRelationshipBuilder(ABC):
    """Contract for building entity relationship graphs from 02-Library/."""

    @abstractmethod
    def build_graph(self, library_dir: Path) -> RelationshipGraph:
        """Scan library entities and compute a weighted relationship graph."""
        ...

    @abstractmethod
    def write_pages(
        self,
        graph: RelationshipGraph,
        relationships_dir: Path,
    ) -> int:
        """Write faction/NPC/location sub-graphs to 04-Relationships/. Return count."""
        ...


# ---------------------------------------------------------------------------
# ICanonValidator (canon agent contract)
# ---------------------------------------------------------------------------

class ICanonValidator(ABC):
    """Contract for validating consistency of approved 02-Library/ entities."""

    @abstractmethod
    def validate(self, library_dir: Path) -> CanonReport:
        """Scan all entities and return canon violations. Read-only."""
        ...


# ---------------------------------------------------------------------------
# ICleaner (cleanup agent contract)
# ---------------------------------------------------------------------------

class ICleaner(ABC):
    """Contract for log/report rotation and metrics trimming."""

    @abstractmethod
    def purge_logs(self, logs_dir: Path, keep_days: int) -> int:
        """Delete log files older than keep_days. Return count deleted."""
        ...

    @abstractmethod
    def purge_reports(self, reports_dir: Path, keep_days: int) -> int:
        """Delete report files older than keep_days. Return count deleted."""
        ...

    @abstractmethod
    def trim_metrics(self, metrics_path: Path, max_runs: int) -> int:
        """Trim each agent's run history to max_runs entries. Return runs removed."""
        ...


# ---------------------------------------------------------------------------
# ICurator (curator agent contract)
# ---------------------------------------------------------------------------

class ICurator(ABC):
    """Contract for scoring drafts for Library promotion readiness."""

    @abstractmethod
    def assess(self, path: Path, frontmatter: dict, body: str) -> CuratorSuggestion:
        """Return promotion readiness assessment for one draft. No I/O."""
        ...


# ---------------------------------------------------------------------------
# ISearchIndexer (search agent contract)
# ---------------------------------------------------------------------------

class ISearchIndexer(ABC):
    """Contract for building and querying a vault entity index."""

    @abstractmethod
    def build(self, dirs: list[Path]) -> SearchIndexState:
        """Index all .md entities in the given vault directories."""
        ...

    @abstractmethod
    def query(
        self,
        index: SearchIndexState,
        q: str,
        *,
        tags: Optional[list[str]] = None,
    ) -> list[SearchEntry]:
        """Return matching entries ranked by keyword relevance."""
        ...


# ---------------------------------------------------------------------------
# IDedupAnalyzer (deduplication agent contract)
# ---------------------------------------------------------------------------

class IDedupAnalyzer(ABC):
    """Contract for detecting duplicate/near-duplicate vault entities."""

    @abstractmethod
    def find_candidates(self, paths: list[Path]) -> list[DedupCandidate]:
        """Return merge candidates above similarity threshold. Read-only."""
        ...


# ---------------------------------------------------------------------------
# IQueueRegistrar (ingestion agent contract)
# ---------------------------------------------------------------------------

class IQueueRegistrar(ABC):
    """Contract for registering 00-Inbox/ files into the processing queue.

    Owned by the Ingestion agent. No LLM calls. No 02-Library writes.
    """

    @abstractmethod
    def classify_file(self, path: Path) -> str:
        """Return 'image', 'document', or 'other' for the given file path."""
        ...

    @abstractmethod
    def make_slots(self, file_type: str) -> InboxQueue:
        """Return initialized agent slots dict for the given file type."""
        ...

    @abstractmethod
    def scan_and_register(self, inbox: Path) -> tuple[int, int]:
        """Scan inbox for unregistered files and add them to the shared queue.

        Returns (count_added, count_failed). Saves atomically.
        Must not delete or overwrite existing queue entries.
        """
        ...


# ---------------------------------------------------------------------------
# ISignalEmitter - file-based inter-agent signal bus
# ---------------------------------------------------------------------------

@runtime_checkable
class ISignalEmitter(Protocol):
    """Structural protocol for emitting inter-agent signals."""

    def emit(
        self,
        signal_type: str,
        emitter: str,
        ref: str = "",
        payload: Optional[dict] = None,
    ) -> str:
        """Write a signal file to the signals directory. Returns signal ID."""
        ...


# ---------------------------------------------------------------------------
# IRegistryLoader - registry.yaml loader contract
# ---------------------------------------------------------------------------

@runtime_checkable
class IRegistryLoader(Protocol):
    """Structural protocol for loading the agent registry from registry.yaml."""

    def load(self, project_root: Path) -> RegistryConfig:
        """Parse .agents/registry.yaml and return a validated RegistryConfig.

        Raises FileNotFoundError if registry.yaml does not exist.
        Raises ValidationError if the YAML does not conform to the schema.
        """
        ...


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMOfflineError(Exception):
    """LLM server unreachable - caller should skip batch, not fail permanently."""


class LLMResponseError(Exception):
    """LLM returned unexpected content after all retries."""


class VaultWriteError(PermissionError):
    """Attempted write to a protected vault directory."""


class DispatchError(Exception):
    """Orchestrator could not dispatch an agent - unknown type, missing config, etc."""


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

