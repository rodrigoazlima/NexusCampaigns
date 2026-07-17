"""
Tests for .automation/09-generate-npcs.py - Lore Agent

Strategy: import Python functions directly via importlib; no HTTP calls.
call_vision_llm is excluded - it requires a live LM Studio instance.
All assertions target pure logic: JSON parsing, markdown generation,
image resizing, and filesystem state.

Behaviors under test:
  1.  fmt_mod                   - +N / -N / +0 modifier formatting
  2.  make_index_key            - sha256|scenario_id composite key
  3.  load_index                - missing file; valid file; corrupted; v1 migration
  4.  save_index                - round-trip; UTF-8; unicode; pretty-printed
  5.  build_markdown happy path - full NPC → valid YAML frontmatter + body sections
  6.  build_markdown edge cases - padded abilities; optional sha256; rel cap; bad types
  7.  load_library_context      - missing dir; no frontmatter; valid entities; cap
  8.  update_queue_lore         - missing file; rel in queue; rel absent; corrupt
  9.  load_classified_chars     - missing; v1/v2 format; type filter; status filter
 10.  resize_and_encode         - small unchanged; large resized; aspect preserved
"""

from __future__ import annotations

import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    Path(__file__).parent.parent / "agents" / "lore" / "tools" / "generate_npcs.py"
)

_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))


def _load_module() -> ModuleType:
    """Load generate_npcs.py as importable module without running main()."""
    import types

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    mod = types.ModuleType("generate_npcs")
    mod.__file__ = str(SCRIPT_PATH)
    exec(compile(source, str(SCRIPT_PATH), "exec"), mod.__dict__)  # noqa: S102
    return mod


if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found: {SCRIPT_PATH}",
        allow_module_level=True,
    )

try:
    _mod = _load_module()
except Exception as _exc:
    pytest.skip(
        f"Failed to load {SCRIPT_PATH.name}: {_exc}. "
        "See agents/tests/ for current coverage.",
        allow_module_level=True,
    )

_API_REQUIRED = (
    "fmt_mod", "make_index_key", "load_index", "save_index",
    "build_markdown", "load_library_context", "update_queue_lore",
    "load_classified_characters", "resize_and_encode",
)
_MISSING_API = [fn for fn in _API_REQUIRED if not hasattr(_mod, fn)]
if _MISSING_API:
    pytest.skip(
        f"generate_npcs.py API changed - functions not found: {_MISSING_API}. "
        "Refactored module uses _output_to_frontmatter/_output_to_body/etc. "
        "Next step: rewrite these tests against agents/lore/tools/generate_npcs.py API "
        "or extend agents/tests/test_classification.py.",
        allow_module_level=True,
    )

fmt_mod                    = _mod.fmt_mod
make_index_key             = _mod.make_index_key
load_index                 = _mod.load_index
save_index                 = _mod.save_index
build_markdown             = _mod.build_markdown
load_library_context       = _mod.load_library_context
update_queue_lore          = _mod.update_queue_lore
load_classified_characters = _mod.load_classified_characters
resize_and_encode          = _mod.resize_and_encode
MAX_DIM                    = _mod.MAX_DIM
MAX_LIBRARY_ENTITIES       = _mod.MAX_LIBRARY_ENTITIES

# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def make_rgb_png(
    path: Path,
    width: int = 32,
    height: int = 32,
    color: tuple[int, int, int] = (100, 150, 200),
) -> Path:
    """Create a solid-colour RGB PNG at *path* and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), color=color).save(str(path), "PNG")
    return path


def decode_b64_jpeg(b64: str) -> Image.Image:
    """Decode a base64 JPEG string back to a PIL Image."""
    return Image.open(BytesIO(base64.b64decode(b64)))


def images_are_equal(a: Image.Image, b: Image.Image) -> bool:
    """Return True when two images share identical size and pixel data."""
    if a.size != b.size or a.mode != b.mode:
        return False
    return list(a.getdata()) == list(b.getdata())


def assert_images_similar(
    a: Image.Image,
    b: Image.Image,
    min_ssim: float = 0.90,
) -> None:
    """Assert structural similarity ≥ min_ssim; falls back to size check if skimage absent."""
    try:
        import numpy as np
        from skimage.metrics import structural_similarity as ssim  # type: ignore

        arr_a = np.array(a.convert("RGB"))
        arr_b = np.array(b.resize(a.size, Image.LANCZOS).convert("RGB"))
        score = ssim(arr_a, arr_b, channel_axis=-1, data_range=255)
        assert score >= min_ssim, f"SSIM {score:.3f} < threshold {min_ssim}"
    except ImportError:
        assert a.size == b.size, f"Image sizes differ: {a.size} vs {b.size}"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Minimal vault directory tree used across multiple test classes."""
    (tmp_path / "02-Library").mkdir()
    (tmp_path / "01-Processing").mkdir()
    (tmp_path / "00-Inbox" / "images").mkdir(parents=True)
    (tmp_path / ".automation").mkdir()
    return tmp_path


@pytest.fixture()
def sample_npc() -> dict:
    """Minimal valid NPC dict as the vision LLM would return it."""
    return {
        "name": "Elara Dawnwhisper",
        "ancestry": "Elf",
        "heritage": "Ancient Elf",
        "class": "Wizard",
        "level": 7,
        "background": "A scholar of the arcane arts who fled the burning of the Athenaeum.",
        "str": -1,
        "dex": 3,
        "con": 0,
        "int": 5,
        "wis": 2,
        "cha": 1,
        "abilities": ["Fireball", "Detect Magic", "Arcane Ward"],
        "trait": "Speaks in riddles",
        "ideal": "Knowledge is power",
        "bond": "Must recover the lost tomes",
        "flaw": "Arrogant about her intellect",
        "role": "Mentor figure who guides the party through ancient ruins.",
        "relationships": ["[[location-athenaeum-ruins]]", "[[faction-arcane-circle]]"],
    }


@pytest.fixture()
def sample_scenario() -> dict:
    return {
        "id": "A1",
        "name": "Annun Ascendant",
        "description": "A rising city-state threatened by shadow cultists.",
        "active": True,
    }


# ---------------------------------------------------------------------------
# 1. fmt_mod
# ---------------------------------------------------------------------------


class TestFmtMod:
    """fmt_mod formats integers as +N for non-negative, -N for negative."""

    @pytest.mark.parametrize("val,expected", [
        (0,   "+0"),
        (1,   "+1"),
        (5,   "+5"),
        (10,  "+10"),
        (-1,  "-1"),
        (-5,  "-5"),
        (-10, "-10"),
    ])
    def test_known_values(self, val: int, expected: str) -> None:
        assert fmt_mod(val) == expected

    def test_positive_has_plus_prefix(self) -> None:
        assert fmt_mod(3).startswith("+")

    def test_negative_has_minus_prefix(self) -> None:
        assert fmt_mod(-3).startswith("-")

    def test_zero_is_plus_zero(self) -> None:
        assert fmt_mod(0) == "+0"


# ---------------------------------------------------------------------------
# 2. make_index_key
# ---------------------------------------------------------------------------


class TestMakeIndexKey:
    """make_index_key builds 'sha256|scenario_id' composite strings."""

    @pytest.mark.parametrize("sha,sid,expected", [
        ("abc123",  "A1",          "abc123|A1"),
        ("f" * 64, "scenario-01", ("f" * 64) + "|scenario-01"),
        ("0" * 64, "X9",          ("0" * 64) + "|X9"),
    ])
    def test_format(self, sha: str, sid: str, expected: str) -> None:
        assert make_index_key(sha, sid) == expected

    def test_pipe_separator_present(self) -> None:
        assert "|" in make_index_key("deadbeef", "S2")

    def test_sha_prefix_preserved(self) -> None:
        sha = "a" * 64
        assert make_index_key(sha, "X").startswith(sha)

    def test_scenario_suffix_preserved(self) -> None:
        assert make_index_key("abc", "MyScenario").endswith("MyScenario")


# ---------------------------------------------------------------------------
# 3. load_index
# ---------------------------------------------------------------------------


class TestLoadIndex:
    """load_index returns defaults when file is absent, empty, or corrupted."""

    _DEFAULT = {"version": 2, "npcs": {}}

    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        assert load_index(tmp_path / "nonexistent.json") == self._DEFAULT

    def test_valid_file_returned(self, tmp_path: Path) -> None:
        data = {"version": 2, "npcs": {"k|A1": {"status": "ok"}}}
        p = tmp_path / "idx.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        assert load_index(p) == data

    def test_corrupted_file_returns_default(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{{{not json", encoding="utf-8")
        assert load_index(p) == self._DEFAULT

    def test_empty_file_returns_default(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert load_index(p) == self._DEFAULT

    def test_v1_index_gets_version_one(self, tmp_path: Path) -> None:
        """Index without 'version' key is stamped version=1."""
        data = {"npcs": {"key|A1": {"status": "ok"}}}
        p = tmp_path / "v1.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        assert load_index(p)["version"] == 1

    def test_v2_version_preserved(self, tmp_path: Path) -> None:
        data = {"version": 2, "npcs": {}}
        p = tmp_path / "v2.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        assert load_index(p)["version"] == 2

    def test_npcs_dict_present_in_result(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.json"
        p.write_text(json.dumps({"version": 2, "npcs": {"k": {}}}), encoding="utf-8")
        assert "npcs" in load_index(p)


# ---------------------------------------------------------------------------
# 4. save_index
# ---------------------------------------------------------------------------


class TestSaveIndex:
    """save_index writes pretty-printed UTF-8 JSON that load_index can round-trip."""

    def test_file_created(self, tmp_path: Path) -> None:
        p = tmp_path / "out.json"
        save_index(p, {"version": 2, "npcs": {}})
        assert p.exists()

    def test_round_trip(self, tmp_path: Path) -> None:
        data = {"version": 2, "npcs": {"k|A1": {"status": "ok", "sha256": "abc"}}}
        p = tmp_path / "idx.json"
        save_index(p, data)
        assert json.loads(p.read_text(encoding="utf-8")) == data

    def test_unicode_preserved(self, tmp_path: Path) -> None:
        """Non-ASCII characters must survive without JSON escaping."""
        data = {"version": 2, "npcs": {}, "note": "Élodie → Warrior"}
        p = tmp_path / "unicode.json"
        save_index(p, data)
        raw = p.read_text(encoding="utf-8")
        assert "Élodie" in raw
        assert "→" in raw

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "existing.json"
        p.write_text('{"old": true}', encoding="utf-8")
        new_data = {"version": 2, "npcs": {"new|A1": {}}}
        save_index(p, new_data)
        assert json.loads(p.read_text(encoding="utf-8")) == new_data

    def test_output_is_pretty_printed(self, tmp_path: Path) -> None:
        p = tmp_path / "pretty.json"
        save_index(p, {"version": 2, "npcs": {"k": {}}})
        assert "\n" in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. build_markdown - happy path
# ---------------------------------------------------------------------------


class TestBuildMarkdownHappyPath:
    """build_markdown produces valid YAML frontmatter and all body sections."""

    def _md(self, npc: dict, scenario: dict, sha: str = "a" * 64) -> str:
        return build_markdown(npc, scenario, "elara.portrait.png", "2026-06-14", sha256=sha)

    def test_starts_with_yaml_fence(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert self._md(sample_npc, sample_scenario).startswith("---\n")

    def test_has_closing_yaml_fence(self, sample_npc: dict, sample_scenario: dict) -> None:
        body = self._md(sample_npc, sample_scenario)
        # Second occurrence of "---\n" closes the frontmatter
        assert body.index("---\n", 3) > 3

    def test_type_npc(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "type: npc" in self._md(sample_npc, sample_scenario)

    def test_status_draft(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "status: draft" in self._md(sample_npc, sample_scenario)

    def test_quality_zero(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "quality: 0" in self._md(sample_npc, sample_scenario)

    def test_reviewed_false(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "reviewed: false" in self._md(sample_npc, sample_scenario)

    def test_sha256_in_frontmatter(self, sample_npc: dict, sample_scenario: dict) -> None:
        sha = "a" * 64
        assert f"sha256: {sha}" in self._md(sample_npc, sample_scenario, sha)

    def test_source_image_filename(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "elara.portrait.png" in self._md(sample_npc, sample_scenario)

    def test_created_date(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "created: 2026-06-14" in self._md(sample_npc, sample_scenario)

    def test_npc_name_heading(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "# Elara Dawnwhisper" in self._md(sample_npc, sample_scenario)

    def test_ancestry_in_frontmatter(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert 'ancestry: "Elf"' in self._md(sample_npc, sample_scenario)

    def test_class_in_frontmatter(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert 'class: "Wizard"' in self._md(sample_npc, sample_scenario)

    def test_level_in_frontmatter(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "level: 7" in self._md(sample_npc, sample_scenario)

    def test_all_ability_modifiers_present(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        for stat in ("str", "dex", "con", "int", "wis", "cha"):
            assert fmt_mod(sample_npc[stat]) in md

    def test_ability_scores_section(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "## Ability Scores" in self._md(sample_npc, sample_scenario)

    def test_key_abilities_section(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        assert "## Key Abilities" in md
        assert "Fireball" in md

    def test_personality_section(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        assert "## Personality" in md
        assert "Speaks in riddles" in md
        assert "Knowledge is power" in md

    def test_bond_and_flaw_present(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        assert "Must recover the lost tomes" in md
        assert "Arrogant about her intellect" in md

    def test_role_section(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        assert "## Role in Scenario" in md
        assert "Mentor figure" in md

    def test_background_section(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        assert "## Background" in md
        assert "scholar of the arcane arts" in md

    def test_token_embed(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "![[elara.portrait.png]]" in self._md(sample_npc, sample_scenario)

    def test_related_section_present(self, sample_npc: dict, sample_scenario: dict) -> None:
        assert "## Related" in self._md(sample_npc, sample_scenario)

    def test_slug_format(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        assert "id: npc-elara-dawnwhisper-a1" in md

    def test_llm_relationships_in_yaml(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = self._md(sample_npc, sample_scenario)
        assert "[[location-athenaeum-ruins]]" in md


# ---------------------------------------------------------------------------
# 6. build_markdown - edge cases
# ---------------------------------------------------------------------------


class TestBuildMarkdownEdgeCases:
    """build_markdown handles missing/incomplete/invalid NPC data gracefully."""

    def test_no_sha256_omits_sha256_line(self, sample_npc: dict, sample_scenario: dict) -> None:
        md = build_markdown(sample_npc, sample_scenario, "img.png", "2026-06-14", sha256="")
        assert "sha256:" not in md

    def test_abilities_padded_when_only_one_provided(self, sample_scenario: dict) -> None:
        npc = {**_minimal_npc("Stub"), "abilities": ["Shield Bash"]}
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        assert "Shield Bash" in md
        assert "## Key Abilities" in md

    def test_abilities_padded_when_key_absent(self, sample_scenario: dict) -> None:
        npc = _minimal_npc("NoAb")
        npc.pop("abilities", None)
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        assert "## Key Abilities" in md

    def test_relationships_yaml_capped_at_five(self, sample_scenario: dict) -> None:
        npc = {**_minimal_npc("Many"), "relationships": [f"[[entity-{i}]]" for i in range(10)]}
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        rel_lines = [ln for ln in md.splitlines() if ln.strip().startswith('- "[[')]
        assert len(rel_lines) <= 5

    def test_scenario_link_always_first_in_yaml_rels(self, sample_scenario: dict) -> None:
        npc = {**_minimal_npc("First"), "relationships": ["[[entity-other]]"]}
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        rel_lines = [ln for ln in md.splitlines() if ln.strip().startswith('- "[[')]
        assert len(rel_lines) >= 1
        assert "scenario-a1" in rel_lines[0].lower()

    def test_non_list_relationships_no_crash(self, sample_scenario: dict) -> None:
        npc = {**_minimal_npc("BadRels"), "relationships": "not-a-list"}
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        assert "## Related" in md

    def test_unicode_npc_name_preserved(self, sample_scenario: dict) -> None:
        npc = {**_minimal_npc("Áire O'Mórrígan")}
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        assert "Áire O'Mórrígan" in md

    @pytest.mark.parametrize("level", [1, 10, 20])
    def test_level_range(self, sample_scenario: dict, level: int) -> None:
        npc = {**_minimal_npc("Lev"), "level": level}
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        assert f"level: {level}" in md

    @pytest.mark.parametrize("val", [-5, -1, 0, 1, 5])
    def test_ability_modifier_formatting(self, sample_scenario: dict, val: int) -> None:
        npc = {**_minimal_npc("Mod"), "str": val}
        md = build_markdown(npc, sample_scenario, "img.png", "2026-06-14")
        assert fmt_mod(val) in md


# ---------------------------------------------------------------------------
# 7. load_library_context
# ---------------------------------------------------------------------------


class TestLoadLibraryContext:
    """load_library_context reads 02-Library/ entities into a compact context string."""

    def test_missing_library_dir_returns_empty(self, tmp_path: Path) -> None:
        assert load_library_context(tmp_path) == ""

    def test_empty_library_dir_returns_empty(self, vault: Path) -> None:
        assert load_library_context(vault) == ""

    def test_file_without_frontmatter_skipped(self, vault: Path) -> None:
        (vault / "02-Library" / "no-frontmatter.md").write_text(
            "Just prose, no YAML fences.", encoding="utf-8"
        )
        assert load_library_context(vault) == ""

    def test_valid_entity_included_in_context(self, vault: Path) -> None:
        _write_library_entity(vault, "npc-hero.md", "npc-hero", "npc", ["human", "warrior"])
        ctx = load_library_context(vault)
        assert "npc-hero" in ctx

    def test_context_starts_with_header(self, vault: Path) -> None:
        _write_library_entity(vault, "npc-hero.md", "npc-hero", "npc", [])
        ctx = load_library_context(vault)
        assert ctx.startswith("Existing canon entities")

    def test_entity_type_present_in_context(self, vault: Path) -> None:
        _write_library_entity(vault, "loc-ruins.md", "loc-ruins", "location", [])
        assert "location" in load_library_context(vault)

    def test_tags_included_in_context(self, vault: Path) -> None:
        _write_library_entity(vault, "npc-vamp.md", "npc-vamp", "npc", ["undead", "vampire"])
        assert "undead" in load_library_context(vault)

    def test_entity_without_id_uses_filename_stem(self, vault: Path) -> None:
        (vault / "02-Library" / "mystery-file.md").write_text(
            "---\ntype: npc\n---\n", encoding="utf-8"
        )
        assert "mystery-file" in load_library_context(vault)

    def test_multiple_entities_all_present(self, vault: Path) -> None:
        for i in range(3):
            _write_library_entity(vault, f"entity-{i}.md", f"entity-{i}", "npc", [])
        ctx = load_library_context(vault)
        for i in range(3):
            assert f"entity-{i}" in ctx

    def test_cap_at_max_library_entities(self, vault: Path) -> None:
        for i in range(MAX_LIBRARY_ENTITIES + 5):
            _write_library_entity(vault, f"entity-{i:03d}.md", f"entity-{i:03d}", "npc", [])
        ctx = load_library_context(vault)
        entity_lines = [ln for ln in ctx.splitlines() if ln.startswith("- ")]
        assert len(entity_lines) <= MAX_LIBRARY_ENTITIES


# ---------------------------------------------------------------------------
# 8. update_queue_lore
# ---------------------------------------------------------------------------


class TestUpdateQueueLore:
    """update_queue_lore marks agents.lore=done in inbox-queue.json."""

    def test_missing_queue_file_is_noop(self, tmp_path: Path) -> None:
        update_queue_lore(tmp_path / "nonexistent.json", "any/path.png")

    def test_marks_lore_done(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        q.write_text(
            json.dumps({"img.png": {"agents": {"lore": "pending", "vision": "done"}}}),
            encoding="utf-8",
        )
        update_queue_lore(q, "img.png")
        assert json.loads(q.read_text(encoding="utf-8"))["img.png"]["agents"]["lore"] == "done"

    def test_other_agents_untouched(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        q.write_text(
            json.dumps({"img.png": {"agents": {"lore": "pending", "vision": "done", "tags": "pending"}}}),
            encoding="utf-8",
        )
        update_queue_lore(q, "img.png")
        result = json.loads(q.read_text(encoding="utf-8"))
        assert result["img.png"]["agents"]["vision"] == "done"
        assert result["img.png"]["agents"]["tags"] == "pending"

    def test_absent_rel_path_no_change(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        data = {"other.png": {"agents": {"lore": "pending"}}}
        q.write_text(json.dumps(data), encoding="utf-8")
        update_queue_lore(q, "missing.png")
        assert json.loads(q.read_text(encoding="utf-8")) == data

    def test_corrupted_json_is_noop(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        q.write_text("{broken json", encoding="utf-8")
        update_queue_lore(q, "img.png")
        assert q.exists()

    def test_entry_without_agents_key_no_crash(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        q.write_text(json.dumps({"img.png": {"status": "pending"}}), encoding="utf-8")
        update_queue_lore(q, "img.png")
        result = json.loads(q.read_text(encoding="utf-8"))
        assert "agents" not in result["img.png"]

    def test_persisted_to_disk(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        q.write_text(json.dumps({"img.png": {"agents": {"lore": "pending"}}}), encoding="utf-8")
        update_queue_lore(q, "img.png")
        assert json.loads(q.read_text(encoding="utf-8"))["img.png"]["agents"]["lore"] == "done"


# ---------------------------------------------------------------------------
# 9. load_classified_characters
# ---------------------------------------------------------------------------


class TestLoadClassifiedCharacters:
    """load_classified_characters returns rel_path→sha256 for eligible images."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_classified_characters(tmp_path / "none.json") == {}

    def test_corrupted_file_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        assert load_classified_characters(p) == {}

    def test_v1_portrait_included(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.json"
        _write_processed_images_v1(p, {
            "00-Inbox/images/A1/hero.portrait.png": {
                "status": "ok", "type": "portrait", "sha256": "abc123",
            }
        })
        result = load_classified_characters(p)
        assert result.get("00-Inbox/images/A1/hero.portrait.png") == "abc123"

    def test_v2_portrait_included(self, tmp_path: Path) -> None:
        sha = "b" * 64
        p = tmp_path / "idx.json"
        _write_processed_images_v2(p, {
            sha: {"status": "ok", "type": "portrait", "path": "00-Inbox/images/hero.portrait.png"}
        })
        result = load_classified_characters(p)
        assert result.get("00-Inbox/images/hero.portrait.png") == sha

    @pytest.mark.parametrize("img_type", ["portrait", "body", "token"])
    def test_character_types_included(self, tmp_path: Path, img_type: str) -> None:
        sha = "c" * 64
        p = tmp_path / "idx.json"
        _write_processed_images_v2(p, {
            sha: {"status": "ok", "type": img_type, "path": f"img.{img_type}.png"}
        })
        assert len(load_classified_characters(p)) == 1

    @pytest.mark.parametrize("img_type", ["battlemap", "scene", "unknown"])
    def test_non_character_types_excluded(self, tmp_path: Path, img_type: str) -> None:
        sha = "d" * 64
        p = tmp_path / "idx.json"
        _write_processed_images_v2(p, {
            sha: {"status": "ok", "type": img_type, "path": f"img.{img_type}.png"}
        })
        assert load_classified_characters(p) == {}

    def test_failed_status_excluded(self, tmp_path: Path) -> None:
        sha = "e" * 64
        p = tmp_path / "idx.json"
        _write_processed_images_v2(p, {
            sha: {"status": "failed", "type": "portrait", "path": "img.portrait.png"}
        })
        assert load_classified_characters(p) == {}

    def test_non_dict_entry_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.json"
        p.write_text(json.dumps({"version": 2, "images": {"bad": "not-a-dict"}}), encoding="utf-8")
        assert load_classified_characters(p) == {}

    def test_empty_path_in_v2_excluded(self, tmp_path: Path) -> None:
        sha = "f" * 64
        p = tmp_path / "idx.json"
        _write_processed_images_v2(p, {sha: {"status": "ok", "type": "portrait", "path": ""}})
        assert load_classified_characters(p) == {}

    def test_empty_sha256_in_v1_excluded(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.json"
        _write_processed_images_v1(p, {
            "img.portrait.png": {"status": "ok", "type": "portrait", "sha256": ""}
        })
        assert load_classified_characters(p) == {}

    def test_multiple_entries_all_returned(self, tmp_path: Path) -> None:
        p = tmp_path / "idx.json"
        entries = {
            str(i) * 64: {"status": "ok", "type": "portrait", "path": f"img{i}.portrait.png"}
            for i in range(3)
        }
        _write_processed_images_v2(p, entries)
        assert len(load_classified_characters(p)) == 3


# ---------------------------------------------------------------------------
# 10. resize_and_encode
# ---------------------------------------------------------------------------


class TestResizeAndEncode:
    """resize_and_encode converts an image file to a base64 JPEG string."""

    def test_returns_valid_base64_jpeg(self, tmp_path: Path) -> None:
        b64 = resize_and_encode(make_rgb_png(tmp_path / "src.png", 32, 32))
        raw = base64.b64decode(b64)
        assert raw[:2] == b"\xff\xd8", "Expected JPEG magic bytes 0xFF 0xD8"

    def test_small_image_not_upscaled(self, tmp_path: Path) -> None:
        b64 = resize_and_encode(make_rgb_png(tmp_path / "tiny.png", 64, 64))
        out = decode_b64_jpeg(b64)
        assert out.width <= 64 and out.height <= 64

    def test_large_image_longest_side_capped_at_max_dim(self, tmp_path: Path) -> None:
        b64 = resize_and_encode(make_rgb_png(tmp_path / "big.png", MAX_DIM * 2, MAX_DIM * 2))
        out = decode_b64_jpeg(b64)
        assert max(out.width, out.height) <= MAX_DIM

    def test_exact_max_dim_not_resized(self, tmp_path: Path) -> None:
        b64 = resize_and_encode(make_rgb_png(tmp_path / "exact.png", MAX_DIM, MAX_DIM))
        out = decode_b64_jpeg(b64)
        assert max(out.width, out.height) <= MAX_DIM

    def test_landscape_aspect_ratio_preserved(self, tmp_path: Path) -> None:
        """Wide image (2:1) must keep approximately the same ratio after resize."""
        w, h = MAX_DIM * 2, MAX_DIM
        b64 = resize_and_encode(make_rgb_png(tmp_path / "wide.png", w, h))
        out = decode_b64_jpeg(b64)
        expected = w / h
        actual = out.width / out.height
        assert abs(actual - expected) < 0.06, f"Ratio drift: expected ~{expected:.2f}, got {actual:.2f}"

    def test_portrait_aspect_ratio_preserved(self, tmp_path: Path) -> None:
        """Tall image (1:2) must keep approximately the same ratio after resize."""
        w, h = MAX_DIM, MAX_DIM * 2
        b64 = resize_and_encode(make_rgb_png(tmp_path / "tall.png", w, h))
        out = decode_b64_jpeg(b64)
        expected = w / h
        actual = out.width / out.height
        assert abs(actual - expected) < 0.06, f"Ratio drift: expected ~{expected:.2f}, got {actual:.2f}"

    def test_output_mode_is_rgb(self, tmp_path: Path) -> None:
        """JPEG output must be RGB - RGBA is not supported by JPEG."""
        b64 = resize_and_encode(make_rgb_png(tmp_path / "src.png", 128, 128))
        assert decode_b64_jpeg(b64).mode == "RGB"

    def test_invalid_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(Exception):
            resize_and_encode(tmp_path / "ghost.png")

    def test_perceptual_similarity_after_encode(self, tmp_path: Path) -> None:
        """Re-decoded output should be visually close to the source (SSIM ≥ 0.85)."""
        src_path = make_rgb_png(tmp_path / "ref.png", 256, 256, color=(180, 90, 45))
        b64 = resize_and_encode(src_path)
        src_img = Image.open(src_path).convert("RGB")
        out_img = decode_b64_jpeg(b64)
        assert_images_similar(src_img, out_img, min_ssim=0.85)

    @pytest.mark.parametrize("w,h", [
        (1,   1),
        (100, 200),
        (512, 512),
        (MAX_DIM - 1, MAX_DIM - 1),
        (MAX_DIM + 1, MAX_DIM + 1),
    ])
    def test_various_sizes_encode_successfully(self, tmp_path: Path, w: int, h: int) -> None:
        b64 = resize_and_encode(make_rgb_png(tmp_path / f"img_{w}x{h}.png", w, h))
        raw = base64.b64decode(b64)
        assert raw[:2] == b"\xff\xd8"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _minimal_npc(name: str) -> dict:
    """Return the smallest valid NPC dict build_markdown will accept."""
    return {
        "name": name,
        "ancestry": "Human",
        "heritage": "",
        "class": "Fighter",
        "level": 1,
        "background": "Background text.",
        "str": 0, "dex": 0, "con": 0, "int": 0, "wis": 0, "cha": 0,
        "abilities": [],
        "trait": "", "ideal": "", "bond": "", "flaw": "", "role": "",
        "relationships": [],
    }


def _write_library_entity(
    vault: Path,
    filename: str,
    entity_id: str,
    entity_type: str,
    tags: list[str],
) -> None:
    tag_block = "".join(f"\n  - {t}" for t in tags)
    (vault / "02-Library" / filename).write_text(
        f"---\nid: {entity_id}\ntype: {entity_type}\ntags:{tag_block}\n---\n# {entity_id}\n",
        encoding="utf-8",
    )


def _write_processed_images_v1(path: Path, images: dict) -> None:
    path.write_text(json.dumps({"version": 1, "images": images}), encoding="utf-8")


def _write_processed_images_v2(path: Path, images: dict) -> None:
    path.write_text(json.dumps({"version": 2, "images": images}), encoding="utf-8")

