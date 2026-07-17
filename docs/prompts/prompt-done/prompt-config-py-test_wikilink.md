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

# tests\test_wikilink.py
"""Tests for wikilink.tools.wikilink_library."""

import json
import sys
from pathlib import Path

import pytest

_AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))

import wikilink.tools.wikilink_library as _mod
from shared import FrontmatterIO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    kb = tmp_path / "knowledge-base"
    (kb / "02-Library").mkdir(parents=True)
    return kb


@pytest.fixture
def patch_roots(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(_mod, "_VAULT_ROOT",   vault)
    monkeypatch.setattr(_mod, "_LIBRARY",      vault / "02-Library")

    agent_state = tmp_path / ".agents" / "wikilink" / "state"
    agent_state.mkdir(parents=True)
    logs_dir = agent_state / "logs"
    logs_dir.mkdir()
    master_log = tmp_path / ".agents" / "runtime" / "state" / "logs" / "automation.log"
    master_log.parent.mkdir(parents=True)
    master_log.touch()

    monkeypatch.setattr(_mod, "_AGENT_STATE", agent_state)
    monkeypatch.setattr(_mod, "_LOGS_DIR",    logs_dir)
    monkeypatch.setattr(_mod, "_MASTER_LOG",  master_log)
    monkeypatch.setattr(_mod, "_STATE_FILE",  agent_state / "wikilink-state.json")

    return vault


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
    def test_mark_and_load_processed(self, vault, patch_roots, tmp_path):
        state_file = tmp_path / ".agents" / "wikilink" / "state" / "wikilink-state.json"
        from shared import StateStore, WIKILINK_STATE_DEFAULT
        store = StateStore(state_file, WIKILINK_STATE_DEFAULT)
        store.init_defaults()

        _mod._mark_processed(store, "knowledge-base/02-Library/npc-witch.md", 3)
        processed = _mod._load_processed(store)
        assert "knowledge-base/02-Library/npc-witch.md" in processed

    def test_init_defaults_idempotent(self, vault, patch_roots, tmp_path):
        state_file = tmp_path / ".agents" / "wikilink" / "state" / "wikilink-state.json"
        from shared import StateStore, WIKILINK_STATE_DEFAULT
        store = StateStore(state_file, WIKILINK_STATE_DEFAULT)
        store.init_defaults()
        store.init_defaults()  # second call must not overwrite
        assert state_file.exists()


# ---------------------------------------------------------------------------
# main() - no library
# ---------------------------------------------------------------------------

class TestMainNoLibrary:
    def test_exits_zero_when_library_missing(self, vault, patch_roots, monkeypatch, tmp_path):
        missing = tmp_path / "knowledge-base" / "02-Library-missing"
        monkeypatch.setattr(_mod, "_LIBRARY", missing)
        with pytest.raises(SystemExit) as exc:
            _mod.main()
        assert exc.value.code == 0


# ---------------------------------------------------------------------------
# main() - happy path
# ---------------------------------------------------------------------------

class TestMainHappyPath:
    def test_processes_batch_and_updates_state(self, vault, patch_roots):
        lib = vault / "02-Library"
        _write_entity(lib, "npc-witch", ["undead"],
                      "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        with pytest.raises(SystemExit) as exc:
            _mod.main()
        assert exc.value.code == 0

        state = json.loads(_mod._STATE_FILE.read_text(encoding="utf-8"))
        assert len(state) == 2

    def test_skips_already_processed(self, vault, patch_roots):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead"],
                               "## Description\nA witch.\n")
        _write_entity(lib, "npc-necromancer", ["undead"],
                      "## Description\nA necromancer.\n")

        # Run once to populate state
        with pytest.raises(SystemExit):
            _mod.main()

        mtime_before = path_a.stat().st_mtime

        # Run again - both already processed, no changes expected
        with pytest.raises(SystemExit):
            _mod.main()

        # File should not have been modified
        assert path_a.stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# Batch size enforcement
# ---------------------------------------------------------------------------

class TestBatchSize:
    def test_batch_capped_at_batch_size(self, vault, patch_roots):
        lib = vault / "02-Library"
        for i in range(25):
            _write_entity(lib, f"npc-entity-{i:02d}", ["npc"],
                          "## Description\nAn entity.\n")

        with pytest.raises(SystemExit):
            _mod.main()

        state = json.loads(_mod._STATE_FILE.read_text(encoding="utf-8"))
        assert len(state) == _mod.BATCH_SIZE


# ---------------------------------------------------------------------------
# CLI args -- --min-score and --max-links
# ---------------------------------------------------------------------------

class TestCLIArgs:
    def test_min_score_zero_inserts_all_candidates(self, vault, patch_roots, monkeypatch):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", [], "## Description\nA witch.\n")
        _write_entity(lib, "npc-guard", [], "## Description\nA guard.\n")

        monkeypatch.setattr("sys.argv", ["wikilink_library.py", "--min-score", "0"])
        with pytest.raises(SystemExit) as exc:
            _mod.main()
        assert exc.value.code == 0
        content = path_a.read_text(encoding="utf-8")
        assert "[[npc-guard]]" in content

    def test_high_min_score_skips_unrelated_pairs(self, vault, patch_roots, monkeypatch):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", [], "## Description\nA witch.\n")
        _write_entity(lib, "npc-guard", [], "## Description\nA guard.\n")

        monkeypatch.setattr("sys.argv", ["wikilink_library.py", "--min-score", "99"])
        with pytest.raises(SystemExit) as exc:
            _mod.main()
        assert exc.value.code == 0
        content = path_a.read_text(encoding="utf-8")
        assert "[[npc-guard]]" not in content

    def test_max_links_one_inserts_single_link(self, vault, patch_roots, monkeypatch):
        lib = vault / "02-Library"
        path_a = _write_entity(lib, "npc-witch", ["undead", "villain"],
                               "## Description\nA witch.\n\n## Related\n")
        for i in range(3):
            _write_entity(lib, f"npc-enemy-{i:02d}", ["undead", "villain"],
                          f"## Description\nEnemy {i}.\n")

        monkeypatch.setattr("sys.argv", ["wikilink_library.py", "--max-links", "1"])
        with pytest.raises(SystemExit) as exc:
            _mod.main()
        assert exc.value.code == 0

        # Count [[...]] links added in Related section
        content = path_a.read_text(encoding="utf-8")
        related_section = content.split("## Related")[-1]
        links = [m for m in related_section.split("\n") if m.startswith("[[")]
        assert len(links) == 1


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

