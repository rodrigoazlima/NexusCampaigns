"""Abstract interfaces for all pipeline components.

No implementation. All methods are abstract or raise NotImplementedError.
Concrete classes live in each agent's tools/ package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from .config import VaultConfig
from .models import (
    AgentMetrics,
    DailyReport,
    EntityFrontmatter,
    InboxQueue,
    ProcessedImagesState,
    ProcessedNPCs,
    RepairReport,
    TagEnrichmentOutput,
    VisionClassification,
    NPCLLMOutput,
)


# ---------------------------------------------------------------------------
# IAgent — every pipeline agent satisfies this contract
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

    Enforces the contract via ABC. Subclasses must define
    TASK_ID, SCRIPT_BASENAME and implement run_batch().

    Bootstrap contract (called before execute()):
      bootstrap() must be called once on first run to initialise any missing
      state files via IStateStore.init_defaults(). Idempotent — safe to call
      on every startup.
    """

    TASK_ID:         str
    SCRIPT_BASENAME: str
    BATCH_SIZE:      int = 10

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

    @abstractmethod
    def execute(self) -> int:
        """Entry point. Calls bootstrap(), emits START/DONE log lines. Returns exit code."""
        ...


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
        Idempotent — never overwrites an existing file.
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
        """Raise PermissionError if target is inside a write-protected dir.
        Protected dirs: 02-Library/, 00-Inbox/.
        """
        ...

    @abstractmethod
    def assert_not_inbox_delete(self, target: Path) -> None:
        """Raise PermissionError if target is inside 00-Inbox/."""
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
# IOrchestrator
# ---------------------------------------------------------------------------

class IOrchestrator(ABC):
    """Contract for the runner — schedules and dispatches agents."""

    @abstractmethod
    def is_due(self, task_id: str) -> bool:
        """Return True if elapsed ≥ intervalSeconds for this task."""
        ...

    @abstractmethod
    def dispatch(self, task_id: str) -> int:
        """Run the agent for task_id as a subprocess. Return exit code."""
        ...

    @abstractmethod
    def commit_changes(self, task_id: str) -> None:
        """git add -A && git commit after a successful agent run."""
        ...


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMOfflineError(Exception):
    """LLM server unreachable — caller should skip batch, not fail permanently."""


class LLMResponseError(Exception):
    """LLM returned unexpected content after all retries."""


class VaultWriteError(PermissionError):
    """Attempted write to a protected vault directory."""
