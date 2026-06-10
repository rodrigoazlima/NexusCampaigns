"""shared — public surface of the vault pipeline's shared layer.

Consumers import from here; never from sub-modules directly.
"""

from .config import LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths
from .entity_scanner import EntityScanner
from .frontmatter_io import FrontmatterIO
from .llm_client import LLMClient
from .loaders import load_vault_config
from .logger import Logger
from .quality_gate import QualityGate
from .slug_utils import (
    entity_id_from_path,
    extract_wikilinks,
    has_wikilink,
    normalize_slug,
    slugs_from_relationships,
    to_slug,
    wikilink,
)
from .state_store import StateStore
from .vault_guard import VaultGuard
from .defaults import (
    CANON_REPORT_DEFAULT,
    DEDUP_REPORT_DEFAULT,
    GENERATED_TOKENS_DEFAULT,
    INBOX_QUEUE_DEFAULT,
    PROCESSED_IMAGES_DEFAULT,
    PROCESSED_NPCS_DEFAULT,
    RELATIONSHIP_GRAPH_DEFAULT,
    REQUIRED_DIRS,
    SCENARIOS_DEFAULT,
    SEARCH_INDEX_DEFAULT,
    STATE_FILE_DEFAULTS,
    TASKS_STATE_DEFAULT,
    TOKEN_LINKS_DEFAULT,
    WIKILINK_STATE_DEFAULT,
)
from .interfaces import (
    BaseAgent,
    DispatchError,
    IAgent,
    ICanonValidator,
    ICleaner,
    ICurator,
    IDedupAnalyzer,
    IFaceMatcher,
    IFrontmatterIO,
    IImageClassifier,
    ILLMClient,
    ILogger,
    INPCGenerator,
    IOrchestrator,
    IQualityGate,
    IRelationshipBuilder,
    IReportBuilder,
    IRunner,
    ISearchIndexer,
    IStateStore,
    ITagEnricher,
    ITokenRenderer,
    IVaultGuard,
    IWikiCompiler,
    IWikilinkResolver,
    LLMOfflineError,
    LLMResponseError,
    VaultWriteError,
)
from .runners import get_runner
from .models import (
    AgentDispatchConfig,
    AgentFolderConfig,
    AgentLogSummary,
    AgentMetrics,
    AgentMetricsEntry,
    AgentSlots,
    AgentSlotStatus,
    CanonReport,
    CanonViolation,
    CanonViolationType,
    CleanupReport,
    CliDispatchConfig,
    ClaudeApiConfig,
    CuratorReport,
    CuratorSuggestion,
    DailyReport,
    DedupCandidate,
    DedupMatchReason,
    DedupReport,
    Element,
    EntityFrontmatter,
    EntityStatus,
    EntityType,
    Environment,
    GeminiApiConfig,
    GeneratedTokenEntry,
    GeneratedTokens,
    ImageProcessStatus,
    ImageType,
    InboxQueue,
    InboxQueueEntry,
    NPCFrontmatter,
    NPCLLMOutput,
    NPCProcessStatus,
    OpenAIApiConfig,
    OpenRouterApiConfig,
    PF2E_ANCESTRIES,
    PF2E_CLASSES,
    PF2E_CREATURE_TYPES,
    ProcessedImageEntry,
    ProcessedImagesState,
    ProcessedNPCEntry,
    ProcessedNPCs,
    RelationshipEdge,
    RelationshipGraph,
    RepairReport,
    ReviewItem,
    RunMetrics,
    RunResult,
    ScenarioEntry,
    SearchEntry,
    SearchIndex,
    SearchIndexState,
    TagEnrichmentOutput,
    TaskConfig,
    TaskDispatchEntry,
    TasksConfig,
    TasksState,
    TaskStateEntry,
    VaultHealthReport,
    VisionClassification,
    WikilinkProcessedEntry,
    WikilinkProcessedState,
)

__all__ = [
    # Config
    "LLMEndpointConfig", "SystemPaths", "VaultConfig", "VaultPaths",
    # Concrete implementations
    "EntityScanner", "FrontmatterIO", "LLMClient", "load_vault_config",
    "Logger", "QualityGate", "StateStore", "VaultGuard",
    # Slug utilities
    "entity_id_from_path", "extract_wikilinks", "has_wikilink",
    "normalize_slug", "slugs_from_relationships", "to_slug", "wikilink",
    # Interfaces
    "BaseAgent", "IAgent", "ICanonValidator", "ICleaner", "ICurator",
    "IDedupAnalyzer", "IFaceMatcher", "IFrontmatterIO", "IImageClassifier",
    "ILLMClient", "ILogger", "INPCGenerator", "IOrchestrator", "IQualityGate",
    "IRelationshipBuilder", "IReportBuilder", "IRunner", "ISearchIndexer",
    "IStateStore", "ITagEnricher", "ITokenRenderer", "IVaultGuard",
    "IWikiCompiler", "IWikilinkResolver",
    # Exceptions
    "DispatchError", "LLMOfflineError", "LLMResponseError", "VaultWriteError",
    # Runners
    "get_runner",
    # Models — enums
    "AgentSlotStatus", "CanonViolationType", "DedupMatchReason", "Element",
    "EntityStatus", "EntityType", "Environment", "ImageProcessStatus",
    "ImageType", "NPCProcessStatus",
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
    "WikilinkProcessedEntry", "WikilinkProcessedState",
    # Models — dispatch config
    "AgentDispatchConfig", "AgentFolderConfig", "CliDispatchConfig",
    "ClaudeApiConfig", "GeminiApiConfig", "OpenAIApiConfig", "OpenRouterApiConfig",
    "RunResult", "TaskDispatchEntry",
    # Models — orchestrator
    "TaskConfig", "TasksConfig", "TasksState", "TaskStateEntry",
    # Models — metrics
    "RunMetrics", "AgentMetricsEntry", "AgentMetrics",
    # Models — reports
    "AgentLogSummary", "CanonReport", "CanonViolation", "CleanupReport",
    "CuratorReport", "CuratorSuggestion", "DailyReport", "DedupCandidate",
    "DedupReport", "RelationshipEdge", "RelationshipGraph", "RepairReport",
    "ReviewItem", "SearchEntry", "SearchIndex", "SearchIndexState",
    "VaultHealthReport",
    # Defaults
    "CANON_REPORT_DEFAULT", "DEDUP_REPORT_DEFAULT",
    "GENERATED_TOKENS_DEFAULT", "INBOX_QUEUE_DEFAULT",
    "PROCESSED_IMAGES_DEFAULT", "PROCESSED_NPCS_DEFAULT",
    "RELATIONSHIP_GRAPH_DEFAULT", "REQUIRED_DIRS", "SCENARIOS_DEFAULT",
    "SEARCH_INDEX_DEFAULT", "STATE_FILE_DEFAULTS", "TASKS_STATE_DEFAULT",
    "TOKEN_LINKS_DEFAULT", "WIKILINK_STATE_DEFAULT",
]
