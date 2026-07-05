"""shared — public surface of the vault pipeline's shared layer.

Consumers import from here; never from sub-modules directly.
"""

from .config import (
    LLMEndpointConfig, SystemPaths, VaultConfig, VaultPaths,
    AppConfig, LLMConfig, LoggingConfig,
    get_config, clear_config_cache,
)
from .entity_scanner import EntityScanner
from .file_lock import FileLock
from .frontmatter_io import FrontmatterIO
from .llm_client import LLMClient
from .loaders import load_registry, load_vault_config
from .logger import Logger, _ensure_utf8_stdout
from .quality_gate import QualityGate
from .queue_store import locked_update_queue_entry
from .slug_utils import (
    build_entity_slug,
    entity_id_from_path,
    extract_wikilinks,
    has_wikilink,
    is_valid_slug,
    normalize_slug,
    slugs_from_relationships,
    to_slug,
    wikilink,
)
from .state_store import StateStore, TextStateStore, bootstrap_vault_state
from .vault_guard import VaultGuard
from .signal_bus import SignalEmitter, SignalConsumer
from .linking_rules import (
    REQUIRED_LINK_GROUPS,
    describe_violations,
    has_required_links,
    is_orphan,
    missing_required_groups,
    required_type_boost,
)
from .defaults import (
    AGENT_METRICS_DEFAULT,
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
    TEXT_STATE_FILES,
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
    IQueueRegistrar,
    IRegistryLoader,
    IRelationshipBuilder,
    IReportBuilder,
    IRunner,
    ISearchIndexer,
    ISignalEmitter,
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
    AgentRegistryEntry,
    AgentSharedStateSpec,
    AgentSlots,
    AgentSlotStatus,
    CanonReport,
    CanonViolation,
    CanonViolationType,
    CleanupReport,
    CliDispatchConfig,
    ClaudeApiConfig,
    ClaudeCodeConfig,
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
    LLMEndpointSpec,
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
    RegistryConfig,
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
    SharedStateFileSpec,
    TagEnrichmentOutput,
    TaskDispatchEntry,
    TasksState,
    TaskStateEntry,
    VaultHealthReport,
    VisionClassification,
    WikilinkProcessedEntry,
    WikilinkProcessedState,
)

__all__ = [
    # Config — Layer 1 (dataclasses)
    "LLMEndpointConfig", "SystemPaths", "VaultConfig", "VaultPaths",
    # Config — Layer 2 (JSON / AppConfig)
    "AppConfig", "LLMConfig", "LoggingConfig", "get_config", "clear_config_cache",
    # Concrete implementations
    "EntityScanner", "FileLock", "FrontmatterIO", "LLMClient", "load_registry", "load_vault_config",
    "Logger", "_ensure_utf8_stdout", "QualityGate", "locked_update_queue_entry",
    "StateStore", "TextStateStore", "bootstrap_vault_state", "VaultGuard",
    # Slug utilities
    "build_entity_slug", "entity_id_from_path", "extract_wikilinks", "has_wikilink",
    "is_valid_slug", "normalize_slug", "slugs_from_relationships", "to_slug", "wikilink",
    # Interfaces
    "BaseAgent", "IAgent", "ICanonValidator", "ICleaner", "ICurator",
    "IDedupAnalyzer", "IFaceMatcher", "IFrontmatterIO", "IImageClassifier",
    "ILLMClient", "ILogger", "INPCGenerator", "IOrchestrator", "IQualityGate",
    "IQueueRegistrar", "IRegistryLoader", "IRelationshipBuilder", "IReportBuilder",
    "IRunner", "ISearchIndexer", "ISignalEmitter", "IStateStore", "ITagEnricher",
    "ITokenRenderer", "IVaultGuard", "IWikiCompiler", "IWikilinkResolver",
    # Exceptions
    "DispatchError", "LLMOfflineError", "LLMResponseError", "VaultWriteError",
    # Linking rules
    "REQUIRED_LINK_GROUPS", "describe_violations", "has_required_links",
    "is_orphan", "missing_required_groups", "required_type_boost",
    # Signal bus
    "SignalEmitter", "SignalConsumer",
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
    "ClaudeApiConfig", "ClaudeCodeConfig", "GeminiApiConfig", "OpenAIApiConfig", "OpenRouterApiConfig",
    "RunResult", "TaskDispatchEntry",
    # Models — runtime
    "TasksState", "TaskStateEntry",
    # Models — metrics
    "RunMetrics", "AgentMetricsEntry", "AgentMetrics",
    # Models — registry
    "AgentRegistryEntry", "AgentSharedStateSpec", "LLMEndpointSpec",
    "RegistryConfig", "SharedStateFileSpec",
    # Models — reports
    "AgentLogSummary", "CanonReport", "CanonViolation", "CleanupReport",
    "CuratorReport", "CuratorSuggestion", "DailyReport", "DedupCandidate",
    "DedupReport", "RelationshipEdge", "RelationshipGraph", "RepairReport",
    "ReviewItem", "SearchEntry", "SearchIndex", "SearchIndexState",
    "VaultHealthReport",
    # Defaults
    "AGENT_METRICS_DEFAULT", "CANON_REPORT_DEFAULT", "DEDUP_REPORT_DEFAULT",
    "GENERATED_TOKENS_DEFAULT", "INBOX_QUEUE_DEFAULT",
    "PROCESSED_IMAGES_DEFAULT", "PROCESSED_NPCS_DEFAULT",
    "RELATIONSHIP_GRAPH_DEFAULT", "REQUIRED_DIRS", "SCENARIOS_DEFAULT",
    "SEARCH_INDEX_DEFAULT", "STATE_FILE_DEFAULTS", "TASKS_STATE_DEFAULT",
    "TEXT_STATE_FILES", "TOKEN_LINKS_DEFAULT", "WIKILINK_STATE_DEFAULT",
]
