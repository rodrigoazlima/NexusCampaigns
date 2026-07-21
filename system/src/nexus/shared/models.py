"""Data contracts for the Vault Nexus Campaigns pipeline.

Pydantic v2 models only - no logic, no I/O, no side effects.
All validation is declarative (field constraints + allowed enums).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EntityType(str, Enum):
    npc            = "npc"
    character      = "character"
    faction        = "faction"
    location       = "location"
    city           = "city"
    village        = "village"
    dungeon        = "dungeon"
    item           = "item"
    artifact       = "artifact"
    quest          = "quest"
    encounter      = "encounter"
    creature       = "creature"
    monster        = "monster"
    event          = "event"
    religion       = "religion"
    organization   = "organization"
    timeline       = "timeline"
    lore           = "lore"


class EntityStatus(str, Enum):
    draft    = "draft"
    review   = "review"
    approved = "approved"
    archived = "archived"


class ImageType(str, Enum):
    portrait  = "portrait"
    body      = "body"
    battlemap = "battlemap"
    scene     = "scene"
    token     = "token"


# Race/CharClass removed as strict enums - PF2e has hundreds of ancestries and
# classes. Open strings are used in VisionClassification instead, validated
# against PF2e vocabulary constants defined below.

# ---------------------------------------------------------------------------
# PF2e open vocabulary constants (used for prompt generation + soft validation)
# ---------------------------------------------------------------------------

PF2E_ANCESTRIES: frozenset[str] = frozenset({
    # Core
    "human", "elf", "dwarf", "halfling", "gnome", "goblin", "leshy",
    "lizardfolk", "ratfolk", "tengu", "catfolk", "orc", "shoony", "anadi",
    "grippli", "automaton", "fleshwarp", "fetchling", "sprite", "kitsune",
    "kobold", "android", "strix", "vanara", "gnoll", "goloma", "hobgoblin",
    "poppet", "shisk", "conrasu", "beastkin", "azarketi",
    # Versatile heritages
    "dhampir", "aasimar", "tiefling", "changeling", "half-elf", "half-orc",
    "duskwalker", "geniekin", "ifrit", "oread", "sylph", "undine",
    "nagaji", "vishkanya", "dark-elf",
    "none",
})

PF2E_CLASSES: frozenset[str] = frozenset({
    "alchemist", "barbarian", "bard", "champion", "cleric", "druid",
    "fighter", "gunslinger", "inventor", "investigator", "kineticist",
    "magus", "monk", "oracle", "psychic", "ranger", "rogue", "sorcerer",
    "summoner", "swashbuckler", "thaumaturge", "witch", "wizard",
    "animist", "exemplar", "commander",
    "none",
})

PF2E_CREATURE_TYPES: frozenset[str] = frozenset({
    "aberration", "animal", "astral", "beast", "celestial", "construct",
    "dragon", "dream", "elemental", "fey", "fiend", "fungus", "giant",
    "humanoid", "monitor", "ooze", "phantom", "plant", "spirit",
    "time", "undead",
    "none",
})


class Element(str, Enum):
    fire     = "fire"
    water    = "water"
    earth    = "earth"
    air      = "air"
    metal    = "metal"
    wood     = "wood"
    nature   = "nature"
    dark     = "dark"
    light    = "light"
    void     = "void"
    vitality = "vitality"
    none     = "none"


class Environment(str, Enum):
    dungeon    = "dungeon"
    cave       = "cave"
    forest     = "forest"
    city       = "city"
    tavern     = "tavern"
    desert     = "desert"
    snow       = "snow"
    sea        = "sea"
    swamp      = "swamp"
    ruins      = "ruins"
    temple     = "temple"
    castle     = "castle"
    plains     = "plains"
    mountain   = "mountain"
    volcano    = "volcano"
    underwater = "underwater"
    sky        = "sky"
    astral     = "astral"
    shadow     = "shadow"
    abyss      = "abyss"
    interior   = "interior"
    exterior   = "exterior"
    none       = "none"


class AgentSlotStatus(str, Enum):
    pending = "pending"
    done    = "done"
    skip    = "skip"
    error   = "error"   # terminal until maintenance/human resets to pending (reruns += 1)
    paused  = "paused"


class ImageProcessStatus(str, Enum):
    ok       = "ok"
    failed   = "failed"
    migrated = "migrated"


class NPCProcessStatus(str, Enum):
    ok           = "ok"
    error_llm    = "error-llm"
    error_image  = "error-image"
    error_write  = "error-write"


# ---------------------------------------------------------------------------
# LLM response contracts
# ---------------------------------------------------------------------------

class VisionClassification(BaseModel):
    """Shape returned by the vision LLM for image classification.

    ancestry / char_class / creature_type are open strings against PF2e vocabulary
    (PF2E_ANCESTRIES / PF2E_CLASSES / PF2E_CREATURE_TYPES).
    Strict enum validation removed - PF2e has too many options to enumerate.
    """
    type:          ImageType
    ancestry:      str       = "none"   # PF2E_ANCESTRIES
    char_class:    str       = Field("none", alias="class")  # PF2E_CLASSES
    creature_type: str       = "none"   # PF2E_CREATURE_TYPES; "none" for PCs/NPCs
    element:       Element   = Element.none
    environment:   Environment = Environment.none
    description:   str       = ""
    # Open brainstorm harvested from the LLM's own visual_analysis block
    # (equipment/clothing/fantasy_features arrays) - never written to note
    # frontmatter; state-only input to the classification agent's tag library.
    candidate_tags: list[str] = Field(default_factory=list)
    # Grounded entity-type guess (EntityType's 18 values, e.g. npc/location/item)
    # from the multi-cycle conversation's dedicated entity-type turn. Open
    # string like ancestry/creature_type - "none" if that cycle never ran or
    # didn't produce a recognized value; _write_draft falls back to its
    # portrait/battlemap placeholder heuristic in that case.
    entity_type: str = "none"

    model_config = {"populate_by_name": True}


class NPCLLMOutput(BaseModel):
    """Shape returned by the lore LLM for NPC generation."""
    name:       str
    ancestry:   str
    heritage:   str         = ""
    char_class: str         = Field("", alias="class")
    level:      Annotated[int, Field(ge=1, le=20)]     = 1
    background: str         = ""
    str_mod:    Annotated[int, Field(ge=-5, le=5, alias="str")]  = 0
    dex_mod:    Annotated[int, Field(ge=-5, le=5, alias="dex")]  = 0
    con_mod:    Annotated[int, Field(ge=-5, le=5, alias="con")]  = 0
    int_mod:    Annotated[int, Field(ge=-5, le=5, alias="int")]  = 0
    wis_mod:    Annotated[int, Field(ge=-5, le=5, alias="wis")]  = 0
    cha_mod:    Annotated[int, Field(ge=-5, le=5, alias="cha")]  = 0
    abilities:  list[str]   = Field(default_factory=list)
    trait:      str         = ""
    ideal:      str         = ""
    bond:       str         = ""
    flaw:       str         = ""
    role:       str         = ""
    relationships: list[str] = Field(default_factory=list)
    description:   str      = ""
    plot_hooks:    list[str] = Field(default_factory=list)
    tactics:       str       = ""
    # Reflexion loop metadata - never comes from LLM; set by _flag_for_human_review
    needs_human_review: bool = False
    review_notes:       str  = ""

    model_config = {"populate_by_name": True}


class TagEnrichmentOutput(BaseModel):
    """Shape returned by the classification LLM."""
    tags: list[str]       = Field(default_factory=list)
    type: Optional[str]   = None


# ---------------------------------------------------------------------------
# Vault entity frontmatter
# ---------------------------------------------------------------------------

class EntityFrontmatter(BaseModel):
    """AGENTS.md-compliant frontmatter for all vault entities."""
    id:                  str
    uuid:                Optional[str]               = None
    type:                EntityType
    status:              EntityStatus                = EntityStatus.draft
    quality:             Annotated[int, Field(ge=0, le=10)] = 0
    created:             date
    updated:             date
    tags:                list[str]                   = Field(default_factory=list)
    source:              list[str]                   = Field(default_factory=list)
    sha256:              Optional[str]               = None
    reviewed:            bool                        = False   # agents never set True
    relationships:       list[str]                   = Field(default_factory=list)
    needs_reprocessing:  bool                        = False
    suggested_quality:   Optional[int]               = None   # set by review agent only


class NPCFrontmatter(EntityFrontmatter):
    """Extended frontmatter for NPC entities."""
    type:       EntityType  = EntityType.npc
    name:       str         = ""
    ancestry:   str         = ""
    heritage:   str         = ""
    char_class: str         = Field("", alias="class")
    level:      Annotated[int, Field(ge=1, le=20)]    = 1
    background: str         = ""
    str_mod:    Annotated[int, Field(ge=-5, le=5, alias="str")] = 0
    dex_mod:    Annotated[int, Field(ge=-5, le=5, alias="dex")] = 0
    con_mod:    Annotated[int, Field(ge=-5, le=5, alias="con")] = 0
    int_mod:    Annotated[int, Field(ge=-5, le=5, alias="int")] = 0
    wis_mod:    Annotated[int, Field(ge=-5, le=5, alias="wis")] = 0
    cha_mod:    Annotated[int, Field(ge=-5, le=5, alias="cha")] = 0
    abilities:  list[str]   = Field(default_factory=list)
    trait:      str         = ""
    ideal:      str         = ""
    bond:       str         = ""
    flaw:       str         = ""
    role:       str         = ""

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Queue / shared state schemas
# ---------------------------------------------------------------------------

class AgentSlots(BaseModel):
    """Per-file agent processing slots inside inbox-queue.json.

    Field order is the canonical pipeline order and is also the display order
    used by the dashboard queue page (rows render agents in JSON key order).
    """
    ingestion:      AgentSlotStatus = AgentSlotStatus.done      # entry exists => file already ingested
    vision:         AgentSlotStatus = AgentSlotStatus.pending
    lore:           AgentSlotStatus = AgentSlotStatus.pending
    classification: AgentSlotStatus = AgentSlotStatus.pending
    wiki:           AgentSlotStatus = AgentSlotStatus.pending
    wikilink:       AgentSlotStatus = AgentSlotStatus.skip       # library-stage agent; n/a to inbox items
    token:          AgentSlotStatus = AgentSlotStatus.skip
    review:         AgentSlotStatus = AgentSlotStatus.pending


class InboxQueueEntry(BaseModel):
    ingestedAt: datetime
    type:       Literal["image", "document", "other"]
    agents:     AgentSlots
    reruns:     dict[str, int] = Field(default_factory=dict)   # per-agent manual reprocess count (dashboard action)


# Type alias - the full queue is a str→entry dict
InboxQueue = dict[str, InboxQueueEntry]


# ---------------------------------------------------------------------------
# Vision agent state
# ---------------------------------------------------------------------------

class ProcessedImageEntry(BaseModel):
    path:         str
    processedAt:  datetime
    originalName: str
    type:          str
    ancestry:      str               = "none"   # open PF2e ancestry
    char_class:    str               = Field("none", alias="class")
    creature_type: str               = "none"   # PF2e creature trait
    element:       str               = "none"
    environment:   str               = "none"
    description:   str               = ""
    sha256:        str
    isToken:       bool              = False
    status:        ImageProcessStatus = ImageProcessStatus.ok

    model_config = {"populate_by_name": True}


class ProcessedImagesState(BaseModel):
    """Root schema for processed-images.json (v2)."""
    version:   int                              = 2
    images:    dict[str, ProcessedImageEntry]   = Field(default_factory=dict)
    pathIndex: dict[str, str]                   = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Lore agent state
# ---------------------------------------------------------------------------

class ProcessedNPCEntry(BaseModel):
    imageKey:     str
    scenarioId:   str
    outputPath:   str
    processedAt:  datetime
    status:       NPCProcessStatus


ProcessedNPCs = dict[str, ProcessedNPCEntry]


class ScenarioEntry(BaseModel):
    id:          str
    name:        str
    description: str
    arc:         str
    active:      bool = True


# ---------------------------------------------------------------------------
# Token agent state
# ---------------------------------------------------------------------------

class GeneratedTokenEntry(BaseModel):
    sourcePath:   str
    tokenPath:    str
    generatedAt:  datetime


GeneratedTokens = dict[str, GeneratedTokenEntry]


# ---------------------------------------------------------------------------
# Agent dispatch configuration (agent.json)
# ---------------------------------------------------------------------------

class CliDispatchConfig(BaseModel):
    command:         str
    args:            list[str]            = Field(default_factory=list)
    cwd:             Literal["project_root", "agent_dir"] = "project_root"
    timeout_seconds: int                  = 300
    env:             dict[str, str]       = Field(default_factory=dict)


class ClaudeCodeConfig(BaseModel):
    prompt_file:     Optional[str]  = None    # relative to agent_dir
    prompt:          Optional[str]  = None    # inline prompt (alt to file)
    extra_args:      list[str]      = Field(default_factory=lambda: ["--dangerously-skip-permissions"])
    cwd:             Literal["project_root", "agent_dir"] = "project_root"
    timeout_seconds: int            = 600
    env:             dict[str, str] = Field(default_factory=dict)


class OpenAIApiConfig(BaseModel):
    base_url:        str
    model:           str
    prompt_file:     Optional[str]        = None
    system_file:     Optional[str]        = None
    max_tokens:      int                  = 1024
    temperature:     float                = 0.0
    timeout_seconds: int                  = 120


class ClaudeApiConfig(BaseModel):
    model:               str
    system_file:         Optional[str]       = None
    tools_module:        Optional[str]       = None   # dotted import path e.g. "repair.tools.repair_agent"
    prompt_file:         Optional[str]       = None   # user prompt .md, relative to agent dir; prompt pattern only
    history_file:        Optional[str]       = None   # relative to agent state/ dir
    max_tokens:          int                 = 4096
    temperature:         float               = 0.0
    timeout_seconds:     int                 = 120
    max_tool_rounds:     int                 = 20
    max_tokens_per_run:  Optional[int]       = None   # abort run if total tokens exceed this


class GeminiApiConfig(BaseModel):
    model:           str
    prompt_file:     Optional[str]        = None
    system_file:     Optional[str]        = None
    max_tokens:      int                  = 2048
    temperature:     float                = 0.0
    timeout_seconds: int                  = 120


class OpenRouterApiConfig(BaseModel):
    model:           str
    prompt_file:     Optional[str]        = None
    system_file:     Optional[str]        = None
    max_tokens:      int                  = 4096
    temperature:     float                = 0.0
    timeout_seconds: int                  = 180


class LmStudioConfig(BaseModel):
    base_url:        str                  = "http://localhost:1234/v1"
    model:           str                  = ""
    max_tokens:      int                  = 64000
    temperature:     float                = 0.0
    timeout_seconds: int                  = 1800
    system_file:     Optional[str]        = None
    prompt_file:     Optional[str]        = None
    tools_module:    Optional[str]        = None   # dotted import path - enables agentic tool-call loop
    history_file:    Optional[str]        = None   # relative to agent state/ dir
    max_tool_rounds: int                  = 20


class CodexCliConfig(BaseModel):
    prompt_file:     Optional[str]        = None
    prompt:          Optional[str]        = None
    model:           str                  = "o4-mini"
    approval_mode:   Literal["suggest", "auto-edit", "full-auto"] = "full-auto"
    extra_args:      list[str]            = Field(default_factory=list)
    cwd:             Literal["project_root", "agent_dir"] = "project_root"
    timeout_seconds: int                  = 600
    env:             dict[str, str]       = Field(default_factory=dict)


class DockerDispatchConfig(BaseModel):
    """Runs the agent's own Dockerfile in a container, bind-mounting the
    shared nexus.shared library (system/), the vault (.knowledge-base/), and
    the agent's own state/ dir straight through - no copy-in/diff/apply, the
    container writes directly to the real host paths. For agents whose code
    lives in an external repo (e.g. nc-vision-agent) cloned into their agent
    folder rather than in-tree."""
    image:           str
    dockerfile:      str                  = "dockerfile"
    timeout_seconds: int                  = 1800
    env:             dict[str, str]       = Field(default_factory=dict)


class AgentDispatchConfig(BaseModel):
    type:           Literal["cli", "openai-api", "claude-api", "gemini-api", "openrouter-api", "claude-code", "lm-studio", "codex-cli", "docker"]
    cli:            Optional[CliDispatchConfig]      = None
    openai_api:     Optional[OpenAIApiConfig]        = None
    claude_api:     Optional[ClaudeApiConfig]        = None
    gemini_api:     Optional[GeminiApiConfig]        = None
    openrouter_api: Optional[OpenRouterApiConfig]    = None
    claude_code:    Optional[ClaudeCodeConfig]       = None
    lm_studio:      Optional[LmStudioConfig]         = None
    codex_cli:      Optional[CodexCliConfig]         = None
    docker:         Optional[DockerDispatchConfig]   = None


class TaskDispatchEntry(BaseModel):
    intervalSeconds:   int
    description:       str
    dispatch:          AgentDispatchConfig
    fallback_dispatch: Optional[AgentDispatchConfig] = None    # tried if primary exits non-zero
    signal_triggers:   list[str] = Field(default_factory=list)
    emits_signals:     list[str] = Field(default_factory=list)


class AgentFolderConfig(BaseModel):
    """Root schema for agent.json - keyed by task ID."""
    cleanupDays: int = 90
    tasks: dict[str, TaskDispatchEntry]


# ---------------------------------------------------------------------------
# Runner result
# ---------------------------------------------------------------------------

class RunResult(BaseModel):
    exit_code:      int
    output:         str            = ""
    error:          Optional[str]  = None
    duration_ms:    int            = 0
    input_tokens:   int            = 0
    output_tokens:  int            = 0
    model:          str            = ""


# ---------------------------------------------------------------------------
# Runtime / task scheduler
# ---------------------------------------------------------------------------

class TaskStateEntry(BaseModel):
    lastRun: datetime


TasksState = dict[str, TaskStateEntry]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class RunMetrics(BaseModel):
    startedAt:      datetime
    finishedAt:     datetime
    durationMs:     int
    itemsProcessed: int = 0
    itemsFailed:    int = 0


class AgentMetricsEntry(BaseModel):
    runs: list[RunMetrics] = Field(default_factory=list)


AgentMetrics = dict[str, AgentMetricsEntry]


# ---------------------------------------------------------------------------
# Report models
# ---------------------------------------------------------------------------

class AgentLogSummary(BaseModel):
    runs:          int                  = 0
    completedRuns: int                  = 0
    errors:        int                  = 0
    warnings:      int                  = 0
    firstRun:      Optional[datetime]   = None
    lastRun:       Optional[datetime]   = None


class VaultHealthReport(BaseModel):
    pendingReview: list[str]            = Field(default_factory=list)
    orphans:       list[str]            = Field(default_factory=list)
    qualityScores: dict[str, int]       = Field(default_factory=dict)
    queueDepth:    int                  = 0
    queuePending:  int                  = 0
    queueDone:     int                  = 0


class TaskCostEntry(BaseModel):
    model:         str
    runs:          int = 0
    input_tokens:  int = 0
    output_tokens: int = 0


class CostSummary(BaseModel):
    date:                str
    by_task:             dict[str, TaskCostEntry] = Field(default_factory=dict)
    total_input_tokens:  int = 0
    total_output_tokens: int = 0


class DailyReport(BaseModel):
    generatedAt:    datetime
    date:           str
    agentSummaries: dict[str, AgentLogSummary] = Field(default_factory=dict)
    vaultHealth:    VaultHealthReport          = Field(default_factory=VaultHealthReport)
    costSummary:    Optional[CostSummary]      = None


class RepairReport(BaseModel):
    date:               str
    generatedAt:        datetime
    fixLabelsDetected:  list[str] = Field(default_factory=list)
    repairsApplied:     int       = 0
    overdueAgents:      list[str] = Field(default_factory=list)
    invalidImageRefs:   list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Review agent - ReviewItem
# ---------------------------------------------------------------------------

class ReviewItem(BaseModel):
    """Per-draft review record produced by the review agent."""
    path:              str
    filename:          str
    id:                str
    type:              EntityType
    status:            EntityStatus
    quality:           Annotated[int, Field(ge=0, le=10)]
    suggested_quality: Optional[int]  = None
    tags:              list[str]       = Field(default_factory=list)
    source:            list[str]       = Field(default_factory=list)
    reviewed:          bool            = False
    relationships:     list[str]       = Field(default_factory=list)
    has_relationships: bool            = False   # len(relationships) > 0
    is_orphan:         bool            = False   # no [[wikilinks]] in body
    needs_reprocessing: bool           = False
    created:           date
    updated:           date
    description:       Optional[str]   = None
    body_lines:        int             = 0


# ---------------------------------------------------------------------------
# Wikilink agent state
# ---------------------------------------------------------------------------

class WikilinkProcessedEntry(BaseModel):
    processedAt:    datetime
    linksInserted:  int = 0


WikilinkProcessedState = dict[str, WikilinkProcessedEntry]


# ---------------------------------------------------------------------------
# Cleanup agent
# ---------------------------------------------------------------------------

class CleanupReport(BaseModel):
    date:            str
    generatedAt:     datetime
    logsDeleted:     int = 0
    reportsDeleted:  int = 0
    metricsTrimmed:  int = 0


# ---------------------------------------------------------------------------
# Relationship agent
# ---------------------------------------------------------------------------

class RelationshipEdge(BaseModel):
    source:       str    # entity id
    target:       str    # entity id
    relation:     str    # "npc_location" | "npc_faction" | "quest_npc" | etc.
    weight:       float  = 1.0   # shared-tag / wikilink score


class RelationshipGraph(BaseModel):
    """Root schema for relationship-graph.json."""
    version:      int                        = 1
    generatedAt:  datetime
    edges:        list[RelationshipEdge]     = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Canon agent
# ---------------------------------------------------------------------------

class CanonViolationType(str, Enum):
    broken_wikilink        = "broken_wikilink"
    missing_relationship   = "missing_relationship"
    duplicate_id           = "duplicate_id"
    missing_required_field = "missing_required_field"
    orphan_entity          = "orphan_entity"


class CanonViolation(BaseModel):
    entity_id:      str
    path:           str
    violation_type: CanonViolationType
    detail:         str


class CanonReport(BaseModel):
    date:              str
    generatedAt:       datetime
    violations:        list[CanonViolation] = Field(default_factory=list)
    entities_scanned:  int = 0
    entities_clean:    int = 0


# ---------------------------------------------------------------------------
# Curator agent
# ---------------------------------------------------------------------------

class CuratorSuggestion(BaseModel):
    path:              str
    id:                str
    type:              EntityType
    quality:           Annotated[int, Field(ge=0, le=10)]
    suggested_quality: Optional[int] = None
    ready:             bool           # quality >= 7 AND reviewed AND has_relationships
    blockers:          list[str]      = Field(default_factory=list)


class CuratorReport(BaseModel):
    generatedAt:   datetime
    date:          str
    suggestions:   list[CuratorSuggestion] = Field(default_factory=list)
    ready_count:   int = 0
    blocked_count: int = 0


# ---------------------------------------------------------------------------
# Search agent
# ---------------------------------------------------------------------------

class SearchEntry(BaseModel):
    id:            str
    path:          str
    type:          EntityType
    title:         str
    tags:          list[str]      = Field(default_factory=list)
    relationships: list[str]      = Field(default_factory=list)
    status:        EntityStatus
    quality:       Annotated[int, Field(ge=0, le=10)]
    body_excerpt:  str            = ""
    indexed_at:    datetime


SearchIndex = dict[str, SearchEntry]   # keyed by entity id


class SearchIndexState(BaseModel):
    """Root schema for search-index.json."""
    version:    int                      = 1
    indexed_at: datetime
    entries:    dict[str, SearchEntry]   = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry - agent-registry.spec.md
# ---------------------------------------------------------------------------

class LLMEndpointSpec(BaseModel):
    """One entry under registry.yaml llm_endpoints."""
    url:      str
    model:    str
    type:     str    # "vision" | "text"
    provider: str
    timeout_seconds: int = 120


class AgentSharedStateSpec(BaseModel):
    """Declares which shared state paths an agent reads / writes / updates."""
    reads:   list[str] = Field(default_factory=list)
    writes:  list[str] = Field(default_factory=list)
    updates: list[str] = Field(default_factory=list)


class SandboxConfig(BaseModel):
    """registry.yaml agents.<name>.sandbox - controls nexus.tasks.sandbox_run's
    apply step, and (via `enabled`) whether the runtime routes this agent's
    normal dispatch through the sandbox instead of running it directly.
    allow_deletes=false (default) means an in-scope file present before a
    sandboxed run but missing after it is dropped, not applied - a rename's
    new file still lands, the stale original is left in place."""
    enabled:       bool = False
    allow_deletes: bool = False


class AgentRegistryEntry(BaseModel):
    """One entry under registry.yaml agents."""
    status:           Literal["active", "planned", "deprecated"]
    task_id:          Optional[str]                 = None
    description:      Optional[str]                 = None
    interval_seconds: Optional[int]                 = None
    llm:              Optional[str]                 = None   # alias or "none"
    tools:            list[str]                     = Field(default_factory=list)
    prompts:          list[str]                     = Field(default_factory=list)
    shared_state:     Optional[AgentSharedStateSpec] = None
    dependencies:     list[str]                     = Field(default_factory=list)
    sandbox:          Optional[SandboxConfig]        = None


class SharedStateFileSpec(BaseModel):
    """One entry under registry.yaml shared_state_files."""
    path:     str
    owner:    str
    updaters: list[str] = Field(default_factory=list)


class DefaultDispatchConfig(BaseModel):
    """registry.yaml `default_dispatch` - fallback used when an agent has no
    agent.json (or no entry for the requested task_id)."""
    type:            str            = "lm-studio"
    base_url:        str            = "http://localhost:1234/v1"
    model:           str            = ""
    timeout_seconds: int            = 1800
    system_file:     Optional[str]  = "prompts/system.md"


class RegistryConfig(BaseModel):
    """Full parsed representation of agents/registry.yaml."""
    version:            int                              = 1
    vault_root:         str
    agents_dir:         str                              = "agents"
    shared_dir:         str                              = "system"
    llm_endpoints:      dict[str, LLMEndpointSpec]       = Field(default_factory=dict)
    execution_order:    list[str]                        = Field(default_factory=list)
    shared_state_files: dict[str, SharedStateFileSpec]   = Field(default_factory=dict)
    agents:             dict[str, AgentRegistryEntry]    = Field(default_factory=dict)
    default_dispatch:   Optional[DefaultDispatchConfig]  = None

    def active_agents(self) -> dict[str, AgentRegistryEntry]:
        """Return only agents with status='active'."""
        return {k: v for k, v in self.agents.items() if v.status == "active"}

    def planned_agents(self) -> dict[str, AgentRegistryEntry]:
        """Return only agents with status='planned'."""
        return {k: v for k, v in self.agents.items() if v.status == "planned"}

    def get_endpoint(self, alias: str) -> Optional[LLMEndpointSpec]:
        """Return LLM endpoint by alias, or None if not found."""
        return self.llm_endpoints.get(alias)


# ---------------------------------------------------------------------------
# Deduplication agent
# ---------------------------------------------------------------------------

class DedupMatchReason(str, Enum):
    slug      = "slug"
    tags      = "tags"
    content   = "content"
    id_prefix = "id_prefix"


class DedupCandidate(BaseModel):
    source_path:      str
    candidate_path:   str
    similarity_score: float
    match_reason:     DedupMatchReason


class DedupReport(BaseModel):
    date:          str
    generatedAt:   datetime
    candidates:    list[DedupCandidate] = Field(default_factory=list)
    files_scanned: int = 0
