"""vision.tools.classify_images

Classifies RPG images in 00-Inbox/images/ via Qwen3-VL.
Renames images to canonical slug format in-place.
Writes AGENTS.md-compliant draft entities to 01-Processing/.
No LLM available → skip gracefully (no images marked failed). Batch: 10 per run.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid as _uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

_TOOLS_DIR    = Path(__file__).resolve().parent
_AGENTS_DIR   = _TOOLS_DIR.parents[1]
_PROJECT_ROOT = _AGENTS_DIR.parent

if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

from nexus.shared import (  # noqa: E402
    FrontmatterIO,
    LLMClient,
    Logger,
    LLMOfflineError,
    LLMResponseError,
    SignalEmitter,
    VisionClassification,
    locked_update_queue_entry,
    sha256_of_file,
    to_slug,
)
from nexus.shared.config import LLMEndpointConfig  # noqa: E402
from nexus.shared.llm_client import _resize_and_encode  # noqa: E402
from nexus.shared.loaders import load_llm_endpoint  # noqa: E402
from nexus.shared.models import Element, Environment, ImageType  # noqa: E402

# classification.tools.enrich_tags owns state/tag-library.json — read-only
# here (cycle 4 aligns against it, never writes it; classification is the
# sole writer of canonical entries/aliases/counts).
_CLASSIFICATION_TAG_LIBRARY = _AGENTS_DIR / "classification" / "state" / "tag-library.json"

# Same 18-value taxonomy as classification agent's _ALLOWED_TYPES
# (agents/classification/tools/enrich_tags.py) — kept in sync manually, same
# convention already used for the PF2E_* vocab lists.
_ENTITY_TYPES: frozenset[str] = frozenset({
    "npc", "character", "faction", "location", "city", "village", "dungeon",
    "item", "artifact", "quest", "encounter", "creature", "monster", "event",
    "religion", "organization", "timeline", "lore",
})

# Adapted from agents/classification/prompts/enrich-tags.txt's dashboard-tab
# guidance — duplicated per this codebase's existing manual-sync convention
# for prompt text (see vision CLAUDE.md's PF2E_* sync note); update both
# together if the taxonomy changes.
_ENTITY_TYPE_GUIDANCE = """Entity types by dashboard tab:

CHARACTERS & NPCS — npc (named non-player character, default for people), character (playable/significant individual)
BESTIARY — creature (reusable monster stat-block), monster (unique/legendary named monster), encounter (a placed fight)
PLACES — location (generic site/region), city, village, dungeon (underground ruin/cave/tomb)
FACTIONS & POWERS — faction (group with a goal/agenda), organization (formal group, no antagonist role), religion
QUESTS & EVENTS — quest (adventure hook), event (past/ongoing event), timeline (sequence of events)
ITEMS & LORE — item (mundane/magical object), artifact (unique powerful relic), lore (world knowledge, not a physical object)

Choose the MOST SPECIFIC type. Prefer dungeon over location for a tomb/cave, creature over npc for a monster, artifact over item for relics."""

_MIN_TAGS_TARGET = 6
_MAX_CONVERSATION_MESSAGES = 10
_VISION_SYSTEM_PROMPT = "You are a Pathfinder 2e image classifier. Return ONLY valid JSON."

# Vision-model token budgets — generous on purpose (assertive over cost-
# efficient): cycle 1's classify-image.txt asks for a large visual_analysis
# JSON that 2048 tokens can truncate mid-object; follow-up cycles return
# smaller JSON but tag lists shouldn't get clipped either.
_CYCLE1_MAX_TOKENS   = 4096
_FOLLOWUP_MAX_TOKENS = 1024

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)

TASK_ID         = "vision-agent"
SCRIPT_BASENAME = "classify_images.py"
BATCH_SIZE      = 10

_VAULT_ROOT   = _PROJECT_ROOT / ".knowledge-base"
_INBOX        = _VAULT_ROOT / "00-Inbox"
_INBOX_IMAGES = _INBOX  # scan entire inbox, not just images/ subdir
_PROCESSING   = _VAULT_ROOT / "01-Processing"
_AGENT_STATE  = _AGENTS_DIR / "vision" / "state"
_LOGS_DIR     = _AGENT_STATE / "logs"
_SHARED_STATE = _PROJECT_ROOT / "system" / "state"
_MASTER_LOG   = _AGENTS_DIR / "runtime" / "state" / "logs" / "automation.log"
_PROC_IMAGES  = _AGENT_STATE / "processed-images.json"
_TOKEN_LINKS  = _AGENT_STATE / "token-links.json"
_QUEUE_FILE   = _SHARED_STATE / "inbox-queue.json"
_GEN_TOKENS   = _AGENTS_DIR / "token" / "state" / "generated-tokens.json"
_PROMPT_FILE  = _AGENTS_DIR / "vision" / "prompts" / "classify-image.txt"
_SIGNALS_DIR  = _AGENTS_DIR / "runtime" / "state" / "signals"

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})

# Types excluded from face-match candidate pool
_EXCLUDE_TYPES = frozenset({"token", "battlemap", "scene"})

_FACE_SIMILARITY_THRESHOLD = 0.85  # cosine similarity for face-region match

# Model selectable via agents/registry.yaml -> llm_endpoints.vision_llm.model
_FALLBACK_LLM_CFG = LLMEndpointConfig(
    url      = "http://localhost:1234/v1/chat/completions",
    model    = "qwen3-vl-4b-instruct",
    type     = "vision",
    provider = "lmstudio",
)


_LLM_CFG = load_llm_endpoint(
    "vision_llm",
    fallback     = _FALLBACK_LLM_CFG,
    agent_dir    = _AGENTS_DIR / "vision",
    task_id      = TASK_ID,
    project_root = _PROJECT_ROOT,
)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

_sha256 = sha256_of_file


# ---------------------------------------------------------------------------
# Token detection
# ---------------------------------------------------------------------------

def _is_token(path: Path) -> bool:
    """Return True if PNG has ≥2 transparent corners — canonical token detection."""
    if path.suffix.lower() != ".png":
        return False
    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        corners = [
            img.getpixel((0, 0)),
            img.getpixel((w - 1, 0)),
            img.getpixel((0, h - 1)),
            img.getpixel((w - 1, h - 1)),
        ]
        return sum(1 for c in corners if c[3] < 128) >= 2
    except Exception:
        return False


# ---------------------------------------------------------------------------
# State I/O  (atomic writes per G8)
# ---------------------------------------------------------------------------

def _load_state() -> dict[str, Any]:
    if not _PROC_IMAGES.exists():
        return {"version": 2, "images": {}, "pathIndex": {}}
    return json.loads(_PROC_IMAGES.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _PROC_IMAGES.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(_PROC_IMAGES)


def _load_token_links() -> dict[str, Any]:
    if not _TOKEN_LINKS.exists():
        return {}
    return json.loads(_TOKEN_LINKS.read_text(encoding="utf-8"))


def _save_token_links(links: dict) -> None:
    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    tmp = _TOKEN_LINKS.with_suffix(".tmp")
    tmp.write_text(json.dumps(links, indent=2, default=str), encoding="utf-8")
    tmp.replace(_TOKEN_LINKS)


def _load_queue() -> dict[str, Any]:
    if not _QUEUE_FILE.exists():
        return {}
    return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Candidate discovery
# ---------------------------------------------------------------------------

def _generated_token_paths() -> set[str]:
    """Project-relative paths of dashboard-generated tokens.

    These artifacts live next to their source in 00-Inbox but are NOT raw input —
    re-ingesting them as new images is what duplicates tokens (each gm/view edit
    writes a differently-named token file; _resolve_image_target then bumps each to
    -01, -02…). Skip them here so they are never treated as source images.
    """
    if not _GEN_TOKENS.exists():
        return set()
    try:
        gen = json.loads(_GEN_TOKENS.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {v["tokenPath"] for v in gen.values() if isinstance(v, dict) and v.get("tokenPath")}


def _candidate_images(state: dict, queue: dict) -> list[Path]:
    """Return unprocessed images, non-PNG first (tokens last per spec)."""
    path_index: set[str] = set(state.get("pathIndex", {}).keys())
    gen_tokens: set[str] = _generated_token_paths()
    images: list[Path] = []
    for path in sorted(_INBOX_IMAGES.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
            continue
        rel = path.relative_to(_PROJECT_ROOT).as_posix()
        if rel in path_index:
            continue
        if rel in gen_tokens:
            continue
        agents = queue.get(rel, {}).get("agents", {})
        if isinstance(agents, dict) and agents.get("vision") in ("done", "paused"):
            continue
        images.append(path)
    return sorted(images, key=lambda p: (p.suffix.lower() == ".png", p))


# ---------------------------------------------------------------------------
# Token face matching
# ---------------------------------------------------------------------------

def _get_folder_candidates(folder: Path, state: dict) -> list[Path]:
    """Return processed non-token, non-battlemap image paths in the same folder.

    Only returns images with a successful state entry (status != failed).
    Used to build the candidate pool for token face matching.
    """
    path_index = state.get("pathIndex", {})
    images     = state.get("images", {})
    candidates: list[Path] = []

    for rel_str, sha_or_key in path_index.items():
        if sha_or_key.startswith("path:"):
            continue  # failed image
        path = _PROJECT_ROOT / rel_str
        if path.parent != folder:
            continue
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        entry = images.get(sha_or_key)
        if not entry or not isinstance(entry, dict):
            continue
        if entry.get("status") == "failed":
            continue
        if entry.get("type") in _EXCLUDE_TYPES:
            continue
        if path.exists():
            candidates.append(path)

    return candidates


def _try_face_match(token_path: Path, candidates: list[Path]) -> Optional[Path]:
    """Match a token to its source portrait via center-crop pixel similarity.

    Uses PIL + numpy only — no heavy dependencies. Falls back to None if
    either dep is missing or any image fails to load.
    Returns the best match above _FACE_SIMILARITY_THRESHOLD, or None.
    """
    if not candidates:
        return None

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    def _face_vector(path: Path) -> Optional[Any]:
        try:
            img = Image.open(path).convert("L")
            w, h = img.size
            # Heuristic face region: horizontal center 40%, vertical upper 50%
            x0, x1 = int(w * 0.3), int(w * 0.7)
            y0, y1 = int(h * 0.1), int(h * 0.6)
            crop = img.crop((x0, y0, x1, y1)).resize((32, 32))
            vec  = np.array(crop, dtype=np.float32).flatten()
            norm = np.linalg.norm(vec)
            return vec / norm if norm > 0 else None
        except Exception:
            return None

    token_vec = _face_vector(token_path)
    if token_vec is None:
        return None

    best_path:  Optional[Path] = None
    best_score: float          = 0.0

    for cand in candidates:
        cand_vec = _face_vector(cand)
        if cand_vec is None:
            continue
        score = float((token_vec * cand_vec).sum())  # cosine sim (vecs are unit-norm)
        if score > best_score:
            best_score = score
            best_path  = cand

    return best_path if best_score >= _FACE_SIMILARITY_THRESHOLD else None


def _inherit_clf_from_state(entry: dict) -> VisionClassification:
    """Rebuild a VisionClassification from a processed-images.json entry.

    Overrides type to `token` — the token inherits all other metadata,
    including the source portrait's final tags/entity_type (same character,
    so both are just as applicable to the token), from its matched source.
    """
    return VisionClassification(
        type           = ImageType.token,
        ancestry       = entry.get("ancestry", "none"),
        **{"class": entry.get("class", "none")},
        creature_type  = entry.get("creature_type", "none"),
        element        = Element(entry.get("element",      "none")),
        environment    = Environment(entry.get("environment", "none")),
        description    = entry.get("description", ""),
        candidate_tags = entry.get("candidate_tags", []),
        entity_type    = entry.get("entity_type", "none"),
    )


# ---------------------------------------------------------------------------
# Slug builders
# ---------------------------------------------------------------------------

def _image_filename_slug(clf: VisionClassification) -> str:
    """Canonical image filename slug per agent-vision.spec.md.

    portrait / body / token : {ancestry}-{class}-{element}.{type}
    battlemap / scene       : {type}-{environment}
    """
    t = clf.type.value
    if t in ("portrait", "body", "token"):
        parts: list[str] = []
        if clf.ancestry and clf.ancestry != "none":
            parts.append(to_slug(clf.ancestry))
        elif clf.creature_type and clf.creature_type != "none":
            parts.append(to_slug(clf.creature_type))
        if clf.char_class and clf.char_class != "none":
            parts.append(to_slug(clf.char_class))
        if clf.element and clf.element.value != "none":
            parts.append(clf.element.value)
        return ("-".join(parts) if parts else "unknown") + f".{t}"
    else:
        env = clf.environment.value if clf.environment.value != "none" else "unknown"
        return f"{t}-{env}"


def _entity_slug(clf: VisionClassification) -> str:
    """Entity slug for the MD file per data-contracts.spec.md: {type}-{descriptors}."""
    t = clf.type.value
    parts = [t]
    if t in ("portrait", "body", "token"):
        if clf.ancestry and clf.ancestry != "none":
            parts.append(to_slug(clf.ancestry))
        elif clf.creature_type and clf.creature_type != "none":
            parts.append(to_slug(clf.creature_type))
        if clf.char_class and clf.char_class != "none":
            parts.append(to_slug(clf.char_class))
        if clf.element and clf.element.value != "none":
            parts.append(clf.element.value)
    else:
        if clf.environment and clf.environment.value != "none":
            parts.append(clf.environment.value)
    return "-".join(parts)


def _resolve_image_target(src: Path, img_slug: str) -> Path:
    """Resolve target path for in-place image rename. Bumps filename on collision."""
    ext    = src.suffix.lower()
    target = src.parent / f"{img_slug}{ext}"
    if not target.exists() or target == src:
        return target
    counter = 1
    while True:
        target = src.parent / f"{img_slug}-{counter:02d}{ext}"
        if not target.exists():
            return target
        counter += 1


def _resolve_entity_path(slug: str) -> Path:
    """Resolve output MD path in 01-Processing/. Bumps on collision."""
    _PROCESSING.mkdir(parents=True, exist_ok=True)
    candidate = _PROCESSING / f"{slug}.md"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = _PROCESSING / f"{slug}-{counter:02d}.md"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Image rename
# ---------------------------------------------------------------------------

def _rename_image(src: Path, clf: VisionClassification) -> Path:
    """Rename image to canonical slug format in-place. Returns new path."""
    img_slug = _image_filename_slug(clf)
    target   = _resolve_image_target(src, img_slug)
    if target != src:
        src.rename(target)
    return target


# ---------------------------------------------------------------------------
# Draft writing
# ---------------------------------------------------------------------------

def _atmosphere_lines(clf: VisionClassification) -> str:
    """Generate atmosphere bullet points from classification data."""
    env  = clf.environment.value if clf.environment.value != "none" else None
    elem = clf.element.value     if clf.element.value     != "none" else None

    lighting_map = {
        "dark":     "Dim, shadowy — torchlight or moonlight only",
        "light":    "Bright and open, natural or magical illumination",
        "fire":     "Flickering orange glow, heat haze near the source",
        "void":     "Absolute darkness with pinpricks of cold starlight",
        "vitality": "Warm golden light, life energy visible as soft radiance",
    }
    mood_map = {
        "dark":     "Dread and tension — something watches from the shadows",
        "fire":     "Urgency and danger — heat presses in from all sides",
        "water":    "Eerie calm, reflections distort what is real",
        "earth":    "Solid and ancient — the weight of stone above is palpable",
        "air":      "Vertiginous openness — wind howls and pulls at equipment",
        "void":     "Cosmic isolation — existence feels fragile here",
        "vitality": "Hopeful and sacred — wounds ache less, resolve strengthens",
        "nature":   "Alive and watching — rustles and growths respond to presence",
        "metal":    "Cold and mechanical — every footstep rings against hard floors",
        "wood":     "Organic and overgrown — roots and vines creep through cracks",
    }
    sound_map = {
        "cave":      "Dripping water, distant echoes, the crunch of gravel underfoot",
        "dungeon":   "Stone settling, faint moans, the scrape of old iron chains",
        "forest":    "Wind through canopy, birdsong that abruptly goes silent",
        "city":      "Crowd murmur, hawkers calling, distant bells",
        "tavern":    "Lute and laughter, the clink of mugs, a fire popping",
        "temple":    "Hollow silence broken by chanting, incense thick in the air",
        "volcano":   "Deep rumbles, hissing steam vents, cracking lava crust",
        "ruins":     "Wind through broken walls, loose stone underfoot, owls",
        "castle":    "Echoing boots on stone, distant orders shouted across battlements",
        "sea":       "Constant wave crash, salt spray, creaking rigging",
        "swamp":     "Frogs, insect chorus, the suck of mud at every step",
        "desert":    "Wind-driven sand, vast silence, the creak of parched wood",
        "snow":      "Muffled sound, breath visible, the creak of ice underfoot",
        "mountain":  "Howling updrafts, distant rockfall, thin air that burns the lungs",
        "underwater": "Muffled rushing, pressure in the ears, bubbles rising",
    }

    atm_lines = [f"- **Setting**: {env.capitalize() if env else 'Unknown'} environment"]
    if elem and elem in lighting_map:
        atm_lines.append(f"- **Lighting**: {lighting_map[elem]}")
    if elem and elem in mood_map:
        atm_lines.append(f"- **Mood**: {mood_map[elem]}")
    if env and env in sound_map:
        atm_lines.append(f"- **Sounds**: {sound_map[env]}")
    return "\n".join(atm_lines)


def _battlemap_body(clf: VisionClassification) -> str:
    env  = clf.environment.value if clf.environment.value != "none" else "unknown"
    elem = clf.element.value     if clf.element.value     != "none" else "none"

    tactical_map: dict[str, list[str]] = {
        "cave":      ["Narrow chokepoints force single-file movement",
                      "Stalagmites provide half-cover; stalactites can be dropped as hazards",
                      "Darkness beyond 30 ft unless light sources are carried"],
        "dungeon":   ["Corridors limit flanking opportunities",
                      "Doorways create fatal-funnel chokepoints",
                      "Rubble and debris create difficult terrain patches"],
        "forest":    ["Trees grant three-quarters cover at range",
                      "Dense undergrowth is difficult terrain (5 ft of movement per 5 ft)",
                      "High canopy may allow flying or climbing ambush"],
        "city":      ["Rooftops accessible for archers — watch vertical threats",
                      "Alleyways split groups; coordinating between lanes is difficult",
                      "Civilians scatter — area spells risk collateral consequences"],
        "ruins":     ["Unstable floors — failing checks drop combatants one level",
                      "Partial walls give half-cover without blocking movement",
                      "Rubble fields are difficult terrain throughout"],
        "volcano":   ["Lava pools deal 4d10 fire damage on contact (or per round)",
                      "Steam vents are hazardous terrain — DC 15 Acrobatics to avoid",
                      "Ground cracks can open as environmental hazards"],
        "temple":    ["Pillars grant cover and can be toppled as an action",
                      "Raised dais gives +1 circumstance bonus on attacks",
                      "Ritual circles on the floor may interact with spells"],
        "sea":       ["Open water = difficult terrain for non-swimmers",
                      "Ship deck limits large creature movement significantly",
                      "Masts and rigging allow Climb DC 15 for high-ground advantage"],
        "castle":    ["Arrow slits grant near-total cover to defenders inside",
                      "Portcullis can be dropped to split the party",
                      "Parapets grant cover and advantage on ranged attacks"],
    }
    hooks_map: dict[str, list[str]] = {
        "cave":    ["Something moves in the deeper darkness — bones crunch underfoot",
                    "A hidden fissure leads to an unexplored passage",
                    "Ancient markings on the walls predate the current inhabitants"],
        "dungeon": ["A cell block holds something that shouldn't still be alive",
                    "The lock mechanism on the far door is set to trap the next opener",
                    "Rations and gear scattered — the previous expedition ended badly here"],
        "forest":  ["Tracks converge on a specific tree — a den or lair above or below",
                    "The silence radius suggests a predator is active nearby",
                    "Fallen shrine in the clearing hints at a forgotten pact"],
        "ruins":   ["A sealed vault door bears a sigil that matches a faction crest",
                    "Fresh campfire ash — someone camped here very recently",
                    "The collapse pattern suggests this wasn't accidental"],
        "volcano": ["Cultists performing a ritual at the caldera edge at midnight",
                    "A heat-warped chest juts from the cooled lava — survivors' cache?",
                    "The eruption cycle is accelerating; the party has limited time"],
        "temple":  ["The altar responds to blood — what does it summon?",
                    "A hidden reliquary behind the main idol holds something valuable",
                    "The priests here serve a god whose name causes the walls to vibrate"],
        "city":    ["A crowd has gathered around something — or someone — on the ground",
                    "Wanted posters on every wall bearing a face that looks familiar",
                    "A merchant's stall is a front; the real business is in the back room"],
    }

    default_tactics = ["Open terrain dominates — movement and positioning are key",
                        "Identify the highest point — height advantage is decisive here",
                        "Flanking lanes are wide; spread out or be surrounded"]
    default_hooks   = ["Something has been disturbed here recently — evidence of passage",
                        "An item of interest is visible but retrieving it is the challenge",
                        "The environment itself becomes an antagonist as the fight progresses"]

    tactics = tactical_map.get(env, default_tactics)
    hooks   = hooks_map.get(env,   default_hooks)

    return (
        f"\n## Description\n\n{clf.description}\n\n"
        f"## Atmosphere\n\n{_atmosphere_lines(clf)}\n\n"
        f"## Tactical Notes\n\n"
        + "\n".join(f"- {t}" for t in tactics) + "\n\n"
        f"## Encounter Hooks\n\n"
        + "\n".join(f"- {h}" for h in hooks) + "\n\n"
        f"## Details\n\n"
        f"- **Type**: Battlemap\n"
        f"- **Environment**: {env}\n"
        f"- **Element**: {elem}\n\n"
        f"## Related\n\n"
    )


def _scene_body(clf: VisionClassification) -> str:
    env  = clf.environment.value if clf.environment.value != "none" else "unknown"
    elem = clf.element.value     if clf.element.value     != "none" else "none"

    hooks_map: dict[str, list[str]] = {
        "cave":      ["A figure stands at the cave mouth — ally, enemy, or something else?",
                      "The light source in this scene will not last much longer",
                      "What the figure sees ahead should terrify any sane adventurer"],
        "dungeon":   ["This is the moment before the door opens — what waits beyond?",
                      "The party must choose: press on or fall back with what they have",
                      "Someone in this image knows more than they are saying"],
        "forest":    ["The encounter began with an arrow — from which direction?",
                      "A figure emerges from the treeline; their intent is unclear",
                      "The beast here is not acting like prey — it is hunting"],
        "volcano":   ["The ritual can still be stopped — but the window is closing",
                      "Escape routes are being cut off by the eruption",
                      "The antagonist has planned for this terrain; the party has not"],
        "city":      ["The crowd turns hostile — who gave the signal?",
                      "The chase leads somewhere the party did not expect",
                      "A witness to something they should not have seen"],
        "interior":  ["The object that matters is somewhere in this room",
                      "The conversation happening here will change everything",
                      "Someone in this scene is lying"],
    }
    default_hooks = [
        "The scene captures a pivotal moment — what came just before?",
        "A detail in the background tells a different story than the foreground",
        "The emotional stakes here can anchor a session's dramatic peak",
    ]
    notes_map: dict[str, list[str]] = {
        "dark":  ["Use this scene at a low point in the campaign arc",
                  "Dim the lights at the table when describing this moment"],
        "fire":  ["Read aloud the heat and urgency — time pressure is the mechanic",
                  "This works as an action climax or an emotional confrontation"],
        "light": ["Scene suggests revelation or triumph — pair with a party achievement",
                  "High contrast lighting suggests a moral choice moment"],
    }
    default_notes = ["Scene works as an establishing shot for a new location or encounter",
                     "Use the description to set the tone before the players act"]

    hooks = hooks_map.get(env,  default_hooks)
    notes = notes_map.get(elem, default_notes)

    return (
        f"\n## Description\n\n{clf.description}\n\n"
        f"## Atmosphere\n\n{_atmosphere_lines(clf)}\n\n"
        f"## Story Hooks\n\n"
        + "\n".join(f"- {h}" for h in hooks) + "\n\n"
        f"## DM Notes\n\n"
        + "\n".join(f"- {n}" for n in notes) + "\n\n"
        f"## Details\n\n"
        f"- **Type**: Scene\n"
        f"- **Environment**: {env}\n"
        f"- **Element**: {elem}\n\n"
        f"## Related\n\n"
    )


def _token_body(clf: VisionClassification) -> str:
    ancestry      = clf.ancestry      if clf.ancestry      != "none" else None
    creature_type = clf.creature_type if clf.creature_type != "none" else None
    char_class    = clf.char_class    if clf.char_class    != "none" else None
    elem          = clf.element.value if clf.element.value != "none" else None

    subject = ancestry or creature_type or "Unknown"
    role_hints: list[str] = []
    if creature_type:
        creature_roles = {
            "dragon":    ["Boss encounter", "Ancient rival", "Unlikely ally with a price"],
            "undead":    ["Recurring villain", "Tragic cursed NPC", "Guardian of a sealed tomb"],
            "fiend":     ["Patron in disguise", "Antagonist pulling strings from afar", "Deal-maker"],
            "celestial": ["Divine messenger", "Quest giver", "Moral compass NPC"],
            "construct": ["Guard automaton", "Arcane experiment escaped", "Loyal servitor"],
            "beast":     ["Wilderness encounter", "Companion animal", "Territorial hazard"],
            "humanoid":  ["Recurring NPC", "Faction representative", "Ambiguous moral agent"],
        }
        role_hints = creature_roles.get(creature_type, ["Encounter creature", "Faction-aligned being"])
    elif ancestry:
        role_hints = ["Player character", "Named NPC ally or rival", "Recurring face in the campaign"]
    else:
        role_hints = ["Unnamed encounter participant", "Background NPC", "Crowd member with a secret"]

    vtt_notes = [
        "512×512 circular portrait — drop directly into Foundry VTT or Roll20",
        "Scale to 1×1 grid square for Medium creatures; 2×2 for Large",
    ]
    if elem:
        vtt_notes.append(f"Consider a {elem}-coloured aura overlay for visual identification")

    return (
        f"\n## Description\n\n{clf.description}\n\n"
        f"## Visual Notes\n\n"
        f"- **Subject**: {subject.capitalize()}"
        + (f" {char_class}" if char_class else "") + "\n"
        + (f"- **Element**: {elem.capitalize()}\n" if elem else "")
        + "\n"
        f"## Suggested Roles\n\n"
        + "\n".join(f"- {r}" for r in role_hints) + "\n\n"
        f"## VTT Usage\n\n"
        + "\n".join(f"- {n}" for n in vtt_notes) + "\n\n"
        f"## Details\n\n"
        f"- **Ancestry**: {clf.ancestry}\n"
        f"- **Class**: {clf.char_class}\n"
        f"- **Creature type**: {clf.creature_type}\n"
        f"- **Element**: {clf.element.value}\n\n"
        f"## Related\n\n"
    )


def _portrait_body(clf: VisionClassification) -> str:
    """Minimal body for portrait/body types — lore agent will enrich these."""
    return (
        f"\n## Description\n\n{clf.description}\n\n"
        f"## Visual Classification\n\n"
        f"- **Ancestry**: {clf.ancestry}\n"
        f"- **Class**: {clf.char_class}\n"
        f"- **Creature type**: {clf.creature_type}\n"
        f"- **Element**: {clf.element.value}\n"
        f"- **Environment**: {clf.environment.value}\n\n"
        f"## Lore Status\n\n"
        f"- Pending NPC sheet generation by Lore Agent\n"
        f"- Classification complete — awaiting scenario pairing\n\n"
        f"## Related\n\n"
    )


def _write_draft(
    path: Path,
    clf: VisionClassification,
    image_path: Path,
    sha256: Optional[str] = None,
    original_image_path: Optional[Path] = None,
) -> str:
    """Writes the draft entity. Returns the resolved entity_type (frontmatter
    'type') so callers can log it distinctly from clf.type (the image's
    structural portrait/body/battlemap/scene/token category) — the two are
    decided by separate, uncoordinated LLM cycles in classify_image_full and
    can disagree (e.g. a confirmed 'scene' image landing on entity_type
    'creature'); logging only clf.type previously hid which value actually
    became the note's type field.

    `original_image_path` is the pre-rename path (_rename_image renames the
    image in-place to its canonical slug before this is called) — when it
    differs from `image_path`, the draft records both under `source`
    (current path) and `originalSource` (as-dropped path/filename), so the
    provenance trail survives the rename instead of only being reconstructable
    after the fact from automation.log timestamps.
    """
    today   = date.today().isoformat()
    slug    = path.stem
    rel_img = image_path.relative_to(_PROJECT_ROOT).as_posix()

    tags: list[str] = [clf.type.value]
    if clf.ancestry and clf.ancestry != "none":
        tags.append(clf.ancestry)
    if clf.creature_type and clf.creature_type != "none":
        tags.append(clf.creature_type)
    if clf.element and clf.element.value != "none":
        tags.append(clf.element.value)
    if clf.environment and clf.environment.value != "none":
        tags.append(clf.environment.value)
    # Final, library-aligned brainstorm from classify_image_full's multi-cycle
    # conversation (state-only until now — this is the one place it becomes
    # the note's actual tags).
    for tag in clf.candidate_tags:
        if tag not in tags:
            tags.append(tag)

    # Grounded guess from the multi-cycle conversation's entity-type cycle
    # takes priority; the coarse portrait/body/token->npc, else->location
    # placeholder only applies when that cycle didn't run or came back "none".
    entity_type = clf.entity_type if clf.entity_type != "none" else (
        "npc" if clf.type.value in ("portrait", "body", "token") else "location"
    )

    frontmatter: dict[str, Any] = {
        "id":            slug,
        "uuid":          str(_uuid.uuid4()),
        "type":          entity_type,
        "status":        "draft",
        "quality":       0,
        "created":       today,
        "updated":       today,
        "tags":          tags,
        "source":        [rel_img],
        "reviewed":      False,
        "relationships": [],
    }
    if sha256:
        frontmatter["sha256"] = sha256
    if original_image_path is not None:
        orig_rel = original_image_path.relative_to(_PROJECT_ROOT).as_posix()
        if orig_rel != rel_img:
            frontmatter["originalSource"] = [orig_rel]

    t = clf.type.value
    if t == "battlemap":
        body = _battlemap_body(clf)
    elif t == "scene":
        body = _scene_body(clf)
    elif t == "token":
        body = _token_body(clf)
    else:
        body = _portrait_body(clf)

    FrontmatterIO().write(path, frontmatter, body)
    return entity_type


# ---------------------------------------------------------------------------
# Candidate tag harvesting
# ---------------------------------------------------------------------------

# Array leaves under the prompt's `visual_analysis` block that name concrete,
# visible things worth surfacing as tag candidates (classify-image.txt already
# asks the LLM for all of these — they were previously parsed and discarded,
# since VisionClassification has no field for them).
_CANDIDATE_TAG_PATHS: tuple[tuple[str, str], ...] = (
    ("equipment", "weapons"),
    ("equipment", "shield"),
    ("equipment", "focus_items"),
    ("equipment", "tools"),
    ("equipment", "musical_instruments"),
    ("equipment", "books"),
    ("equipment", "other"),
    ("clothing", "materials"),
    ("clothing", "ornaments"),
    ("fantasy_features", "creatures"),
    ("fantasy_features", "wings"),
    ("fantasy_features", "horns"),
    ("fantasy_features", "tail"),
    ("fantasy_features", "halo"),
    ("environment_details", "architecture"),
    ("environment_details", "vegetation"),
)


def _extract_candidate_tags(raw: dict) -> list[str]:
    """Flatten visual_analysis array leaves into a deduped raw tag list.

    Best-effort: any shape surprise in the LLM's free-text visual_analysis
    block yields [] rather than failing classification over a tagging extra.
    """
    try:
        analysis = raw.get("visual_analysis") or {}
        seen: dict[str, None] = {}
        for section, key in _CANDIDATE_TAG_PATHS:
            for item in (analysis.get(section) or {}).get(key) or []:
                if not isinstance(item, str):
                    continue
                norm = item.strip().lower()
                if norm:
                    seen.setdefault(norm, None)
        return list(seen)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Multi-cycle classification — image stays in one conversation across up to
# _MAX_CONVERSATION_MESSAGES messages: a clean cold call, then dedicated
# image-type, entity-type, and tag-library-refinement follow-ups. Completion
# goal: >= _MIN_TAGS_TARGET tags + both categories set. No message budget for
# corrective retry turns — a cycle whose response fails to parse just keeps
# whatever was already collected instead of spending a "please retry" turn.
# ---------------------------------------------------------------------------

def _parse_json_response(raw: str) -> dict:
    """Strip a leading/trailing ```json fence before parsing, if present.

    Observed live this session: LocalRouter's `auto` model sometimes wraps
    otherwise-valid JSON in a markdown code fence. Cheap insurance, not a
    correctness risk — falls through to plain json.loads when there's no fence.
    """
    text = raw.strip()
    m = _JSON_FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def _read_tag_library() -> dict[str, Any]:
    """Read-only view of classification agent's canonical tag library."""
    try:
        return json.loads(_CLASSIFICATION_TAG_LIBRARY.read_text(encoding="utf-8"))
    except Exception:
        return {"tags": {}}


def _image_content_block(img_path: Path) -> dict:
    b64 = _resize_and_encode(img_path)
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def _cycle2_prompt(tags_so_far: list[str]) -> str:
    remaining = max(0, _MIN_TAGS_TARGET - len(tags_so_far))
    return (
        "Confirm the image category and continue tagging.\n\n"
        "Category — respond with exactly one of: portrait, body, battlemap, scene, token.\n\n"
        f"We have {len(tags_so_far)} tag(s) so far: {', '.join(tags_so_far) or 'none'}. "
        "List additional short (1-3 word) concrete tags describing objects, materials, "
        f"subjects, or themes visible in the image, not already listed"
        + (f" — aim for at least {remaining} more so the total reaches {_MIN_TAGS_TARGET}." if remaining else ".")
        + '\n\nReturn ONLY valid JSON:\n{"category": "...", "additional_tags": ["...", "..."]}'
    )


def _cycle3_prompt(tags_so_far: list[str]) -> str:
    remaining = max(0, _MIN_TAGS_TARGET - len(tags_so_far))
    return (
        "Now determine the entity type this image will become once promoted "
        "into our Dungeon Master's knowledge base.\n\n"
        f"{_ENTITY_TYPE_GUIDANCE}\n\n"
        f"We have {len(tags_so_far)} tag(s) so far: {', '.join(tags_so_far) or 'none'}. "
        "List any additional concrete tags not yet mentioned"
        + (f" — aim for at least {remaining} more so the total reaches {_MIN_TAGS_TARGET}." if remaining else ".")
        + '\n\nReturn ONLY valid JSON:\n{"entity_type": "...", "additional_tags": ["...", "..."]}'
    )


def _cycle4_prompt(current_tags: list[str], known_tags: list[str], entity_type_hint: str) -> str:
    return (
        "Here is our tag library — canonical tags already in use elsewhere in "
        f"this knowledge base: {', '.join(known_tags) or 'none yet'}\n\n"
        f"Our current tag list for this image: {', '.join(current_tags) or 'none'}\n\n"
        "Align these tags: where a known tag above means the same thing as one of "
        "ours, prefer the known spelling. Finalize the complete tag list for this "
        f"image (merge, dedupe, keep concrete and specific), aiming for at least "
        f"{_MIN_TAGS_TARGET} total if the image supports it. Confirm the entity "
        f"type (current best guess: {entity_type_hint}).\n\n"
        'Return ONLY valid JSON:\n{"final_tags": ["...", "..."], "entity_type": "..."}'
    )


def refine_tags_with_library(
    img_path: Path,
    client: LLMClient,
    current_tags: list[str],
    entity_type_hint: str,
    library: dict[str, Any],
    *,
    history: Optional[list[dict]] = None,
) -> tuple[list[str], str]:
    """Cycle 4, standalone-callable: align current_tags against the tag
    library's known canonical tags and finalize tags + entity type, image
    still in context. Public so other agents/system code can re-run just
    this refinement later (e.g. after the library has grown) without
    redoing the full classification — pass history=None for a fresh
    conversation, or an existing message list to extend it in place.
    """
    known_tags = sorted(
        library.get("tags", {}),
        key=lambda t: -library["tags"][t].get("count", 0),
    )[:20]
    prompt_text = _cycle4_prompt(current_tags, known_tags, entity_type_hint)

    if history is not None:
        messages = history
        messages.append({"role": "user", "content": prompt_text})
    else:
        messages = [
            {"role": "system", "content": _VISION_SYSTEM_PROMPT},
            {"role": "user", "content": [_image_content_block(img_path), {"type": "text", "text": prompt_text}]},
        ]

    if len(messages) + 1 > _MAX_CONVERSATION_MESSAGES:
        # Over budget even before this turn's reply — accept what we have
        # rather than exceed the message cap.
        return current_tags, entity_type_hint

    final_tags, entity_type = current_tags, entity_type_hint
    try:
        raw_text = client.chat(messages, max_tokens=_FOLLOWUP_MAX_TOKENS)
        messages.append({"role": "assistant", "content": raw_text})
        resp = _parse_json_response(raw_text)
        candidate = resp.get("final_tags")
        if isinstance(candidate, list) and candidate:
            final_tags = [t.strip().lower() for t in candidate if isinstance(t, str) and t.strip()]
        et = resp.get("entity_type")
        if isinstance(et, str) and et in _ENTITY_TYPES:
            entity_type = et
    except (LLMOfflineError, LLMResponseError, Exception):
        pass  # graceful degrade — keep current_tags/entity_type_hint as-is

    return final_tags, entity_type


def classify_image_full(
    img_path: Path,
    client: LLMClient,
    prompt: str,
    is_tk: bool,
) -> VisionClassification:
    """Full multi-cycle classification, image held in one conversation:
    (1) clean cold call — existing classify-image.txt prompt, unchanged,
    (2) confirm image type + more tags, (3) infer entity type + more tags,
    (4) tag-library refinement (refine_tags_with_library). Public — the
    single entry point other agents/system code should call for a from-image
    classification. Raises LLMOfflineError / LLMResponseError from cycle 1
    only (matches the old single-call contract callers already handle);
    later cycles degrade gracefully instead of failing the whole image.
    """
    messages: list[dict] = [
        {"role": "system", "content": _VISION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                _image_content_block(img_path),
                {"type": "text", "text": prompt or "Classify this RPG image. Return JSON only."},
            ],
        },
    ]

    # --- Cycle 1: clean — errors propagate, same contract as the old single call ---
    raw_text = client.chat(messages, max_tokens=_CYCLE1_MAX_TOKENS)
    messages.append({"role": "assistant", "content": raw_text})
    raw = _parse_json_response(raw_text)
    clf = VisionClassification.model_validate(raw)
    if is_tk:
        clf = clf.model_copy(update={"type": ImageType.token})
    tags: list[str] = list(dict.fromkeys(_extract_candidate_tags(raw)))

    # --- Cycle 2: image type + more tags ---
    try:
        messages.append({"role": "user", "content": _cycle2_prompt(tags)})
        raw_text = client.chat(messages, max_tokens=_FOLLOWUP_MAX_TOKENS)
        messages.append({"role": "assistant", "content": raw_text})
        resp = _parse_json_response(raw_text)
        cat = resp.get("category")
        if not is_tk and isinstance(cat, str) and cat in {"portrait", "body", "battlemap", "scene", "token"}:
            clf = clf.model_copy(update={"type": ImageType(cat)})
        for t in resp.get("additional_tags") or []:
            if isinstance(t, str) and t.strip():
                norm = t.strip().lower()
                if norm not in tags:
                    tags.append(norm)
    except (LLMOfflineError, LLMResponseError, Exception):
        pass  # keep cycle 1's type/tags — never fail the image over this

    # --- Cycle 3: entity type + more tags ---
    entity_type = "none"
    try:
        messages.append({"role": "user", "content": _cycle3_prompt(tags)})
        raw_text = client.chat(messages, max_tokens=_FOLLOWUP_MAX_TOKENS)
        messages.append({"role": "assistant", "content": raw_text})
        resp = _parse_json_response(raw_text)
        et = resp.get("entity_type")
        if isinstance(et, str) and et in _ENTITY_TYPES:
            entity_type = et
        for t in resp.get("additional_tags") or []:
            if isinstance(t, str) and t.strip():
                norm = t.strip().lower()
                if norm not in tags:
                    tags.append(norm)
    except (LLMOfflineError, LLMResponseError, Exception):
        pass

    # --- Cycle 4: tag-library refinement (in-conversation) ---
    final_tags, entity_type = refine_tags_with_library(
        img_path, client, tags, entity_type, _read_tag_library(), history=messages,
    )

    return clf.model_copy(update={"candidate_tags": final_tags, "entity_type": entity_type})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log = Logger(
        task_id=TASK_ID,
        script_basename=SCRIPT_BASENAME,
        logs_dir=_LOGS_DIR,
        master_log=_MASTER_LOG,
    )
    t0 = log.start()

    _AGENT_STATE.mkdir(parents=True, exist_ok=True)
    _PROCESSING.mkdir(parents=True, exist_ok=True)

    client = LLMClient(_LLM_CFG)
    if not client.is_available():
        log.warning("Qwen3-VL (localhost:1234) offline — skipping batch")
        log.done(t0, key="classified", count=0, failed=0)
        sys.exit(0)

    prompt      = _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists() else ""
    state       = _load_state()
    token_links = _load_token_links()
    queue       = _load_queue()
    candidates  = _candidate_images(state, queue)

    if not candidates:
        log.info("No unprocessed images found")
        log.done(t0, key="classified", count=0, failed=0)
        sys.exit(0)

    batch   = candidates[:BATCH_SIZE]
    count   = 0
    failed  = 0
    emitter = SignalEmitter(_SIGNALS_DIR)
    log.info(f"Batch: {len(batch)} of {len(candidates)} image(s)")

    for img_path in batch:
        orig_img_path = img_path  # pre-rename Path — _rename_image reassigns img_path below
        orig_rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
        is_tk    = _is_token(img_path)

        # --- Classification: face match for tokens, LLM for everything else ---
        clf: Optional[VisionClassification] = None
        matched_source: Optional[Path]      = None

        if is_tk:
            folder_candidates = _get_folder_candidates(img_path.parent, state)
            matched_source    = _try_face_match(img_path, folder_candidates)
            if matched_source is not None:
                matched_rel = matched_source.relative_to(_PROJECT_ROOT).as_posix()
                matched_sha = state["pathIndex"].get(matched_rel)
                if matched_sha and not matched_sha.startswith("path:"):
                    entry = state["images"].get(matched_sha)
                    if entry:
                        clf = _inherit_clf_from_state(entry)
                        log.info(
                            f"Token {img_path.name} → face-matched to "
                            f"{matched_source.name} (inherited meta)"
                        )

        if clf is None:
            try:
                clf = classify_image_full(img_path, client, prompt, is_tk)
            except LLMOfflineError:
                # LM Studio can only hold one model loaded at a time; a
                # concurrent request for another model briefly evicts this
                # one. One retry after a short wait rides out that swap
                # instead of aborting the whole batch.
                log.warning(f"LLM offline while processing {img_path.name} — retrying once")
                time.sleep(10)
                try:
                    clf = classify_image_full(img_path, client, prompt, is_tk)
                except LLMOfflineError:
                    log.warning(f"LLM still offline for {img_path.name} — aborting batch")
                    break
            except (LLMResponseError, Exception) as exc:
                log.error(f"Classification failed for {img_path.name}: {exc}")
                sha_fail = _sha256(img_path)
                state["images"][f"path:{orig_rel}"] = {
                    "uuid":          str(_uuid.uuid4()),
                    "path":          orig_rel,
                    "processedAt":   datetime.now(timezone.utc).isoformat(),
                    "originalName":  img_path.name,
                    "type":          "unknown",
                    "ancestry":      "none",
                    "class":         "none",
                    "creature_type": "none",
                    "element":       "none",
                    "environment":   "none",
                    "description":   "",
                    "candidate_tags": [],
                    "sha256":        sha_fail,
                    "isToken":       is_tk,
                    "status":        "failed",
                }
                state["pathIndex"][orig_rel] = f"path:{orig_rel}"
                _save_state(state)
                failed += 1
                continue

        # --- Rename image (steps 4–6) ---
        try:
            img_path = _rename_image(img_path, clf)
        except Exception as exc:
            log.warning(f"Could not rename {img_path.name}: {exc} — using original path")

        new_rel = img_path.relative_to(_PROJECT_ROOT).as_posix()
        sha     = _sha256(img_path)

        # --- Write draft (step 7) ---
        e_slug   = _entity_slug(clf)
        out_path = _resolve_entity_path(e_slug)
        entity_type = _write_draft(
            out_path, clf, img_path, sha256=sha, original_image_path=orig_img_path,
        )

        log.info(
            f"Classified: {img_path.name} → {out_path.name} "
            f"(image_type={clf.type.value}, entity_type={entity_type})"
        )

        # --- Update processed-images.json (step 9) ---
        state["images"][sha] = {
            "uuid":          state.get("images", {}).get(sha, {}).get("uuid") or str(_uuid.uuid4()),
            "path":          new_rel,
            "processedAt":   datetime.now(timezone.utc).isoformat(),
            "originalName":  img_path.name,
            "type":          clf.type.value,
            "ancestry":      clf.ancestry,
            "class":         clf.char_class,
            "creature_type": clf.creature_type,
            "element":       clf.element.value,
            "environment":   clf.environment.value,
            "description":   clf.description,
            "candidate_tags": clf.candidate_tags,
            "entity_type":   clf.entity_type,
            "sha256":        sha,
            "isToken":       is_tk,
            "status":        "ok",
        }
        state["pathIndex"][new_rel] = sha
        _save_state(state)

        # --- Track face-match link in token-links.json ---
        if is_tk and matched_source is not None:
            matched_rel = matched_source.relative_to(_PROJECT_ROOT).as_posix()
            matched_sha = state["pathIndex"].get(matched_rel, "")
            token_links[sha] = {
                "tokenPath":   new_rel,
                "sourcePath":  matched_rel,
                "sourceSha256": matched_sha,
                "linkedAt":    datetime.now(timezone.utc).isoformat(),
            }
            _save_token_links(token_links)

        # --- Update inbox-queue.json (step 10) — locked, one item at a time ---
        if orig_rel in queue and isinstance(queue[orig_rel].get("agents"), dict):
            def _mark_vision_done(entry: dict) -> Optional[str]:
                entry.setdefault("agents", {})["vision"] = "done"
                entry["candidate_tags"] = clf.candidate_tags
                # Rename queue key to match new image path so classification/lore
                # can trace source frontmatter back to the correct queue entry.
                return new_rel if new_rel != orig_rel else None

            locked_update_queue_entry(_QUEUE_FILE, orig_rel, _mark_vision_done)
            queue = _load_queue()

        # --- Emit signal for Lore agent (fire-and-forget per G5) ---
        emitter.emit(
            signal_type="image-classified",
            emitter=TASK_ID,
            ref=img_path.name,
        )

        count += 1

    log.done(t0, key="classified", count=count, failed=failed)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Agentic tool interface (claude-api dispatch)
# ---------------------------------------------------------------------------

from nexus.shared.agent_tools import SELF_MANAGEMENT_TOOLS, call_self_management_tool  # noqa: E402

_MODULE_FILE = Path(__file__)

TOOLS = SELF_MANAGEMENT_TOOLS + [
    {
        "name": "list_pending_images",
        "description": "Return JSON list of image paths in 00-Inbox/images/ not yet classified.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "detect_token",
        "description": (
            "Check whether a PNG image is a circular token "
            "(transparent corner/edge pixels). Returns {is_token, path}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the PNG image",
                },
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "match_token_face",
        "description": (
            "Attempt to match a token image to its source portrait via face distance. "
            "Returns {matched: bool, source_path?, score?}. "
            "Only meaningful for PNG images detected as tokens."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the token PNG image",
                },
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "classify_image",
        "description": (
            "Classify a single image via the local vision LLM "
            "(type, ancestry, class, element, environment). "
            "Returns JSON classification. Does NOT rename the file or write a draft."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the image file",
                },
            },
            "required": ["image_path"],
        },
    },
    {
        "name": "run_batch",
        "description": (
            "Classify up to BATCH_SIZE pending images, rename them to canonical slugs, "
            "and write draft entities to 01-Processing/. "
            "Returns log output including count processed."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, args: dict, context: dict) -> str:
    import io
    import contextlib
    import json as _json

    result = call_self_management_tool(
        name, args, context, module_file=_MODULE_FILE, task_id=TASK_ID
    )
    if result is not None:
        return result

    if name == "list_pending_images":
        state      = _load_state()
        queue      = _load_queue()
        candidates = _candidate_images(state, queue)
        return _json.dumps([str(p) for p in candidates[:20]])

    if name == "detect_token":
        p = Path(args["image_path"])
        return _json.dumps({"is_token": _is_token(p), "path": str(p)})

    if name == "match_token_face":
        p = Path(args["image_path"])
        if not p.exists():
            return _json.dumps({"error": f"Image not found: {p}"})
        state       = _load_state()
        folder_cands = _get_folder_candidates(p.parent, state)
        matched     = _try_face_match(p, folder_cands)
        if matched is None:
            return _json.dumps({"matched": False, "candidates_checked": len(folder_cands)})
        return _json.dumps({
            "matched":     True,
            "source_path": str(matched),
        })

    if name == "classify_image":
        p = Path(args["image_path"])
        if not p.exists():
            return _json.dumps({"error": f"Image not found: {p}"})
        client = LLMClient(_LLM_CFG)
        if not client.is_available():
            return _json.dumps({"error": "LLM offline (localhost:1234)"})
        prompt = _PROMPT_FILE.read_text(encoding="utf-8") if _PROMPT_FILE.exists() else ""
        is_tk  = _is_token(p)
        try:
            clf = classify_image_full(p, client, prompt, is_tk)
            data = clf.model_dump()
            data["is_token"] = is_tk
            return _json.dumps(data)
        except LLMOfflineError:
            return _json.dumps({"error": "LLM offline"})
        except Exception as exc:
            return _json.dumps({"error": str(exc)})

    if name == "run_batch":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main()
        except SystemExit:
            pass
        return buf.getvalue().strip() or "Batch run complete"

    raise ValueError(f"Unknown tool: {name!r}")
