"""Tests for nexus.workers.wikilink."""

import json
import sys
from pathlib import Path

import pytest

_AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

import nexus.workers.base as _base
import nexus.workers.wikilink as _mod
from nexus.shared import FrontmatterIO

BATCH_SIZE = 20  # registry.yaml workers.wikilink.batch_size


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    kb = tmp_path / ".knowledge-base"
    (kb / "02-Library").mkdir(parents=True)
    return kb


@pytest.fixture
def patch_roots(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(_mod, "_VAULT_ROOT",   vault)
    monkeypatch.setattr(_mod, "_LIBRARY",      vault / "02-Library")
    monkeypatch.setattr(_mod, "_LEGACY_STATE_FILES", ())

    master_log = tmp_path / "agents" / "runtime" / "state" / "logs" / "automation.log"
    master_log.parent.mkdir(parents=True)
    master_log.touch()

    # worker_state_dir / make_worker_logger read these base globals at call time
    monkeypatch.setattr(_base, "WORKERS_STATE_ROOT", tmp_path / "system" / "state" / "workers")
    monkeypatch.setattr(_base, "MASTER_LOG", master_log)

    return vault


def _state_file(tmp_path: Path) -> Path:
    return tmp_path / "system" / "state" / "workers" / "wikilink" / "state.json"


def _run(options: dict | None = None, batch_size: int = BATCH_SIZE) -> list:
    """One worker cycle: pending() capped at batch_size, handle each item."""
    worker = _mod.create(options)
    return [worker.handle(item) for item in worker.pending()[:batch_size]]


def _write_entity(library: Path, slug: str, tags: list[str], body: str) -> Path:
    """Write a minimal entity markdown file into 02-Library/."""
    path = library / f"{slug}.md"
    fm = (
        f"---\nid: {slug}\ntype: npc\nstatus: approved\nreviewed: true\n"
        f"quality: 8\ntags:\n"
        + "".join(f"  - {t}\n" for t in tags)
        + "relationships: []\n---\n"
    )
    path.write_text(fm + body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_strips_stop_words(self):
        kw = _mod._extract_keywords("The necromancer raises the dead with dark magic")
        assert "necromancer" in kw
        assert "raises" in kw
        assert "the" not in kw
        assert "with" not in kw

    def test_min_length_four(self):
        kw = _mod._extract_keywords("big bad wolf ran")
        assert "wolf" in kw
        assert "bad" not in kw   # 3 chars
        assert "ran" not in kw   # 3 chars

    def test_returns_frozenset(self):
        assert isinstance(_mod._extract_keywords("hello world"), frozenset)


# ---------------------------------------------------------------------------
# _splice_related
# ---------------------------------------------------------------------------

class TestSpliceRelated:
    def test_inserts_into_existing_section(self):
        body = "## Description\nA mage.\n\n## Related\n[[existing-link]]\n"
        new_body, count = _mod._splice_related(body, ["npc-witch", "location-tower"])
        assert count == 2
        assert "[[npc-witch]]" in new_body
        assert "[[location-tower]]" in new_body
        assert "[[existing-link]]" in new_body

    def test_creates_section_when_absent(self):
        body = "## Description\nA mage.\n"
        new_body, count = _mod._splice_related(body, ["npc-witch"])
        assert count == 1
        assert "## Related\n[[npc-witch]]" in new_body

    def test_no_duplicates(self):
        body = "## Related\n[[npc-witch]]\n"
        new_body, count = _mod._splice_related(body, ["npc-witch"])
        assert count == 0
        assert new_body.count("[[npc-witch]]") == 1

    def test_empty_slug_list(self):
        body = "## Related\n"
        new_body, count = _mod._splice_related(body, [])
        assert count == 0
        assert new_body == body


# ---------------------------------------------------------------------------
# WikilinkResolver.build_slug_index
# ---------------------------------------------------------------------------

class TestBuildSlugIndex:
    def test_returns_slug_to_path_map(self, vault, patch_roots):
        lib = vault / "02-Library"
        _write_entity(lib, "npc-witch", ["npc"], "A witch.")
        _write_entity(lib, "location-swamp", ["location"], "A swamp.")

        resolver = _mod.WikilinkResolver(FrontmatterIO())
        idx = resolver.build_slug_index(lib)

        assert "npc-witch" in idx
        assert "location-swamp" in idx
        assert idx["npc-witch"].name == "npc-witch.md"

    def test_empty_when_library_missing(self, tmp_path):
        resolver = _mod.WikilinkResolver(FrontmatterIO())
        idx = resolver.build_slug_index(tmp_path / "nonexistent")
        assert idx == {}


# ---------------------------------------------------------------------------
# WikilinkResolver.insert_wikilinks
# ---------------------------------------------------------------------------

class TestInsertWikilinks:
    def test_inserts_link_for_shared_tags(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead", "villain"],
                               "## Description\nA dark witch.\n\n## Related\n")
        _write_entity(lib, "npc-necromancer", ["undead", "villain"],
                      "## Description\nA necromancer.\n")

        resolver = _mod.WikilinkResolver(FrontmatterIO(), min_score=1)
        idx = resolver.build_slug_index(lib)
        n = resolver.insert_wikilinks(path_a, idx)
        assert n >= 1
        content = path_a.read_text(encoding="utf-8")
        assert "[[npc-necromancer]]" in content

    def test_no_self_link(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Description\nA witch.\n\n## Related\n")

        resolver = _mod.WikilinkResolver(FrontmatterIO(), min_score=1)
        idx = resolver.build_slug_index(lib)
        resolver.insert_wikilinks(path_a, idx)
        content = path_a.read_text(encoding="utf-8")
        assert content.count("[[npc-witch]]") == 0

    def test_no_duplicate_links(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Related\n[[npc-necromancer]]\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        resolver = _mod.WikilinkResolver(FrontmatterIO(), min_score=1)
        idx = resolver.build_slug_index(lib)
        resolver.insert_wikilinks(path_a, idx)
        content = path_a.read_text(encoding="utf-8")
        assert content.count("[[npc-necromancer]]") == 1

    def test_creates_related_section_if_absent(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        resolver = _mod.WikilinkResolver(FrontmatterIO(), min_score=1)
        idx = resolver.build_slug_index(lib)
        n = resolver.insert_wikilinks(path_a, idx)
        assert n >= 1
        content = path_a.read_text(encoding="utf-8")
        assert "## Related" in content

    def test_explicit_wikilink_in_body_scores_highest(self, vault, patch_roots):
        lib = vault / "02-Library"
        # npc-witch explicitly references location-tower in body
        path_a = _write_entity(lib, "npc-witch", ["npc"],
                               "## Description\nShe lives in [[location-tower]].\n\n## Related\n")
        _write_entity(lib, "location-tower", ["location"],
                      "## Description\nA dark tower.\n")
        _write_entity(lib, "npc-guard", ["npc"],
                      "## Description\nA guard.\n")

        resolver = _mod.WikilinkResolver(FrontmatterIO(), min_score=1, max_links=1)
        idx = resolver.build_slug_index(lib)
        resolver.insert_wikilinks(path_a, idx)
        content = path_a.read_text(encoding="utf-8")
        # location-tower should win (explicit wikilink = score +3)
        assert "[[location-tower]]" in content

    def test_respects_max_links(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead", "villain", "dark"],
                               "## Description\nA witch.\n\n## Related\n")
        for i in range(5):
            _write_entity(lib, f"npc-enemy-{i:02d}", ["undead", "villain", "dark"],
                          f"## Description\nEnemy {i}.\n")

        resolver = _mod.WikilinkResolver(FrontmatterIO(), min_score=1, max_links=2)
        idx = resolver.build_slug_index(lib)
        n = resolver.insert_wikilinks(path_a, idx)
        assert n == 2

    def test_atomic_write_leaves_no_tmp_file(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        resolver = _mod.WikilinkResolver(FrontmatterIO(), min_score=1)
        idx = resolver.build_slug_index(lib)
        resolver.insert_wikilinks(path_a, idx)

        tmp = path_a.with_name(path_a.name + ".tmp")
        assert not tmp.exists()

    def test_frontmatter_unchanged(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        fio = FrontmatterIO()
        fm_before, _ = fio.read(path_a)

        resolver = _mod.WikilinkResolver(fio, min_score=1)
        idx = resolver.build_slug_index(lib)
        resolver.insert_wikilinks(path_a, idx)

        fm_after, _ = fio.read(path_a)
        assert fm_before == fm_after


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

class TestStateHelpers:
    def test_mark_records_processed_entry(self, vault, patch_roots, tmp_path):
        worker = _mod.create()
        worker._mark(".knowledge-base/02-Library/npc-witch.md", 3)
        state = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert ".knowledge-base/02-Library/npc-witch.md" in state
        assert state[".knowledge-base/02-Library/npc-witch.md"]["linksInserted"] == 3

    def test_init_defaults_idempotent(self, vault, patch_roots, tmp_path):
        _mod.create()
        _mod.create()  # second instance must not clobber state
        assert _state_file(tmp_path).exists()


# ---------------------------------------------------------------------------
# pending() - no library
# ---------------------------------------------------------------------------

class TestPendingNoLibrary:
    def test_empty_when_library_missing(self, vault, patch_roots, monkeypatch, tmp_path):
        missing = tmp_path / ".knowledge-base" / "02-Library-missing"
        monkeypatch.setattr(_mod, "_LIBRARY", missing)
        assert _mod.create().pending() == []


# ---------------------------------------------------------------------------
# Worker cycle - happy path
# ---------------------------------------------------------------------------

class TestWorkerHappyPath:
    def test_processes_batch_and_updates_state(self, vault, patch_roots, tmp_path):
        lib = vault / "02-Library"
        _write_entity(lib, "npc-witch", ["undead"],
                      "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        results = _run()
        assert all(r.status == "done" for r in results)

        state = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert len(state) == 2

    def test_skips_already_processed(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        _run()  # populates state
        mtime_before = path_a.stat().st_mtime

        # Second cycle - both already processed, pending() must be empty
        assert _mod.create().pending() == []
        assert path_a.stat().st_mtime == mtime_before

    def test_approved_frontmatter_untouched(self, vault, patch_roots):
        # Hard invariant: handle() never writes frontmatter
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        fm_before = path_a.read_text(encoding="utf-8").split("---")[1]
        _run()
        fm_after = path_a.read_text(encoding="utf-8").split("---")[1]
        assert fm_before == fm_after


# ---------------------------------------------------------------------------
# Batch size enforcement (runner slices pending() at batch_size)
# ---------------------------------------------------------------------------

class TestBatchSize:
    def test_batch_capped_at_batch_size(self, vault, patch_roots, tmp_path):
        lib = vault / "02-Library"
        for i in range(25):
            _write_entity(lib, f"npc-entity-{i:02d}", ["npc"],
                          "## Description\nAn entity.\n")

        _run(batch_size=BATCH_SIZE)

        state = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert len(state) == BATCH_SIZE


# ---------------------------------------------------------------------------
# Worker options - min_score and max_links
# ---------------------------------------------------------------------------

class TestWorkerOptions:
    def test_min_score_zero_inserts_all_candidates(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", [], "## Description\nA witch.\n")
        _write_entity(lib, "npc-guard", [], "## Description\nA guard.\n")

        _run({"min_score": 0})
        content = path_a.read_text(encoding="utf-8")
        assert "[[npc-guard]]" in content

    def test_high_min_score_skips_unrelated_pairs(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", [], "## Description\nA witch.\n")
        _write_entity(lib, "npc-guard", [], "## Description\nA guard.\n")

        _run({"min_score": 99})
        content = path_a.read_text(encoding="utf-8")
        assert "[[npc-guard]]" not in content

    def test_max_links_one_inserts_single_link(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead", "villain"],
                               "## Description\nA witch.\n\n## Related\n")
        for i in range(3):
            _write_entity(lib, f"npc-enemy-{i:02d}", ["undead", "villain"],
                          f"## Description\nEnemy {i}.\n")

        _run({"max_links": 1})

        # Count [[...]] links added in Related section
        content = path_a.read_text(encoding="utf-8")
        related_section = content.split("## Related")[-1]
        links = [m for m in related_section.split("\n") if m.startswith("[[")]
        assert len(links) == 1
