"""shared — public surface of the vault pipeline's shared layer.

Consumers import from here; never from sub-modules directly.
"""

from .config import LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths
from .defaults import (
    GENERATED_TOKENS_DEFAULT,
    INBOX_QUEUE_DEFAULT,
    PROCESSED_IMAGES_DEFAULT,
    PROCESSED_NPCS_DEFAULT,
    REQUIRED_DIRS,
    SCENARIOS_DEFAULT,
    STATE_FILE_DEFAULTS,
    TASKS_STATE_DEFAULT,
    TOKEN_LINKS_DEFAULT,
)
from .interfaces import (
    BaseAgent,
    IAgent,
    IFaceMatcher,
    IFrontmatterIO,
    IImageClassifier,
    ILLMClient,
    ILogger,
    INPCGenerator,
    IOrchestrator,
    IReportBuilder,
    IStateStore,
    ITagEnricher,
    ITokenRenderer,
    IVaultGuard,
    IWikiCompiler,
    LLMOfflineError,
    LLMResponseError,
    VaultWriteError,
)
from .models import (
    AgentLogSummary,
    AgentMetrics,
    AgentMetricsEntry,
    AgentSlots,
    AgentSlotStatus,
    DailyReport,
    Element,
    EntityFrontmatter,
    EntityStatus,
    EntityType,
    Environment,
    GeneratedTokenEntry,
    GeneratedTokens,
    ImageProcessStatus,
    ImageType,
    InboxQueue,
    InboxQueueEntry,
    NPCFrontmatter,
    NPCLLMOutput,
    NPCProcessStatus,
    PF2E_ANCESTRIES,
    PF2E_CLASSES,
    PF2E_CREATURE_TYPES,
    ProcessedImageEntry,
    ProcessedImagesState,
    ProcessedNPCEntry,
    ProcessedNPCs,
    RepairReport,
    RunMetrics,
    ScenarioEntry,
    TagEnrichmentOutput,
    TaskConfig,
    TasksConfig,
    TasksState,
    TaskStateEntry,
    VaultHealthReport,
    VisionClassification,
)

__all__ = [
    # Config
    "LLMEndpointConfig", "SystemPaths", "VaultConfig", "VaultPaths",
    # Interfaces
    "BaseAgent", "IAgent", "IFaceMatcher", "IFrontmatterIO",
    "IImageClassifier", "ILLMClient", "ILogger", "INPCGenerator",
    "IOrchestrator", "IReportBuilder", "IStateStore", "ITagEnricher",
    "ITokenRenderer", "IVaultGuard", "IWikiCompiler",
    # Exceptions
    "LLMOfflineError", "LLMResponseError", "VaultWriteError",
    # Models — enums
    "AgentSlotStatus", "Element", "EntityStatus", "EntityType",
    "Environment", "ImageProcessStatus", "ImageType", "NPCProcessStatus",
    # Models — PF2e vocabulary
    "PF2E_ANCESTRIES", "PF2E_CLASSES", "PF2E_CREATURE_TYPES",
    # Models — entities
    "EntityFrontmatter", "NPCFrontmatter",
    # Models — LLM contracts
    "NPCLLMOutput", "TagEnrichmentOutput", "VisionClassification",
    # Models — queue / state
    "AgentSlots", "InboxQueue", "InboxQueueEntry",
    "ProcessedImageEntry", "ProcessedImagesState",
    "ProcessedNPCEntry", "ProcessedNPCs",
    "GeneratedTokenEntry", "GeneratedTokens",
    "ScenarioEntry",
    # Models — orchestrator
    "TaskConfig", "TasksConfig", "TasksState", "TaskStateEntry",
    # Models — metrics
    "RunMetrics", "AgentMetricsEntry", "AgentMetrics",
    # Models — reports
    "AgentLogSummary", "DailyReport", "RepairReport", "VaultHealthReport",
    # Defaults
    "GENERATED_TOKENS_DEFAULT", "INBOX_QUEUE_DEFAULT",
    "PROCESSED_IMAGES_DEFAULT", "PROCESSED_NPCS_DEFAULT",
    "REQUIRED_DIRS", "SCENARIOS_DEFAULT", "STATE_FILE_DEFAULTS",
    "TASKS_STATE_DEFAULT", "TOKEN_LINKS_DEFAULT",
]
