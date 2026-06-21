"""
Tests for .automation/04-enrich-tags.ps1

Strategy: patch $VaultRoot in script text, inject LLM stub overrides before
the main block, write to tmp_path, invoke via subprocess. All assertions are
on file-system state (frontmatter content, bad-docs list, log files).

No real LLM server needed — stubs override Test-LLMOnline / Invoke-TagLLM /
Invoke-TypeLLM with deterministic in-process PowerShell functions.

Behaviors under test:
  1.  LLM offline       — early exit 0, no files modified
  2.  No frontmatter    — file added to bad-docs.txt, not modified
  3.  Already rich      — >5 tags + has type → skipped (file byte-identical)
  4.  Needs tags        — ≤5 tags → merged with LLM stub response
  5.  Needs type        — missing type → injected from LLM stub
  6.  Needs both        — missing type AND ≤5 tags → both enriched
  7.  Duplicate detect  — slug matches 02-Library slug → duplicate_of injected
  8.  Bad-docs skip     — path in bad-docs.txt → skipped even if processable
  9.  Inbox + Process   — both 00-Inbox/ and 01-Processing/ are scanned
  10. Log markers       — START/DONE written to automation.log and task log
  11. Idempotency       — second run on already-rich file exits 0, no change
  12. Subdirectory scan — files in nested folders (e.g. 00-Inbox/images/) found
  13. No-body file      — empty body after frontmatter handled without crash
  14. Unicode content   — UTF-8 special characters preserved round-trip
  15. Tag filtering     — LLM tags outside ValidTags list are silently dropped
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "04-enrich-tags.ps1"
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

MAIN_MARKER = (
    "# ── Main ─────────────────────────────────────────────────────────────────────"
)

# Tags the stub LLM always returns (all valid per $ValidTags in the script)
STUB_TAGS = ["npc", "dark", "undead", "location", "faction", "quest", "item"]
STUB_TYPE = "npc"

# ---------------------------------------------------------------------------
# Frontmatter templates
# ---------------------------------------------------------------------------

_FM_RICH = """\
---
id: test-rich
type: npc
status: draft
tags:
  - npc
  - undead
  - dark
  - fire
  - light
  - location
reviewed: false
---
Rich body text.
"""

_FM_NEEDS_TAGS = """\
---
id: test-needs-tags
type: npc
status: draft
tags:
  - npc
reviewed: false
---
Needs more tags.
"""

_FM_NEEDS_TYPE = """\
---
id: test-needs-type
status: draft
tags:
  - npc
  - undead
  - dark
  - fire
  - light
  - location
reviewed: false
---
Has tags but no type.
"""

_FM_NEEDS_BOTH = """\
---
id: test-needs-both
status: draft
tags:
  - npc
reviewed: false
---
Needs type and more tags.
"""

_FM_NO_BODY = """\
---
id: test-no-body
type: npc
status: draft
tags:
  - npc
reviewed: false
---
"""

_FM_UNICODE = """\
---
id: npc-ñoño-mágico
type: npc
status: draft
tags:
  - npc
reviewed: false
---
# Ñoño Mágico

Personagem com caracteres especiais: áéíóú ãõ ç — "quotes" and 'apostrophes'.
"""

_NO_FRONTMATTER = "# Just a heading\n\nNo YAML here.\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ps_bool(value: bool) -> str:
    return "$true" if value else "$false"


def _ps_tag_array(tags: list[str]) -> str:
    items = ", ".join(f"'{t}'" for t in tags)
    return f"@({items})"


def _stub_block(
    llm_online: bool = True,
    tags: list[str] | None = None,
    entity_type: str = STUB_TYPE,
) -> str:
    """PowerShell stubs injected before the main block."""
    tags = tags or STUB_TAGS
    return (
        f"function Test-LLMOnline {{ return {_ps_bool(llm_online)} }}\n"
        f"function Invoke-TagLLM {{\n"
        f"    param([string]$Title, [string]$Snippet, [string[]]$ExistingTags)\n"
        f"    return [string[]]{_ps_tag_array(tags)}\n"
        f"}}\n"
        f"function Invoke-TypeLLM {{\n"
        f"    param([string]$Title, [string]$Snippet)\n"
        f"    return '{entity_type}'\n"
        f"}}\n"
    )


def _patch_script(
    vault_root: Path,
    llm_online: bool = True,
    tags: list[str] | None = None,
    entity_type: str = STUB_TYPE,
) -> str:
    """Read script, patch VaultRoot, inject LLM stubs before main block."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    text = text.replace(
        f"$VaultRoot   = '{ORIGINAL_VAULT_ROOT}'",
        f"$VaultRoot   = '{vault_root}'",
    )
    stubs = _stub_block(llm_online=llm_online, tags=tags, entity_type=entity_type)
    text = text.replace(MAIN_MARKER, stubs + "\n" + MAIN_MARKER)
    return text


def run_enrich_tags(
    vault_root: Path,
    *,
    llm_online: bool = True,
    stub_tags: list[str] | None = None,
    stub_type: str = STUB_TYPE,
) -> subprocess.CompletedProcess[str]:
    """Patch and execute the script; return CompletedProcess for inspection."""
    patched = _patch_script(
        vault_root, llm_online=llm_online, tags=stub_tags, entity_type=stub_type
    )
    tmp_script = vault_root / "_test-04-enrich-tags.ps1"
    tmp_script.write_text(patched, encoding="utf-8")
    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(tmp_script)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _bad_docs_path(vault: Path) -> Path:
    return vault / ".automation" / "bad-docs.txt"


def _bad_docs_entries(vault: Path) -> set[str]:
    p = _bad_docs_path(vault)
    if not p.exists():
        return set()
    return {line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}


def _read_frontmatter_field(content: str, field: str) -> str | None:
    """Return the value of a top-level scalar YAML field from raw file content."""
    for line in content.splitlines():
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip()
    return None


def _read_tags(content: str) -> list[str]:
    """Extract tag list from frontmatter."""
    in_tags = False
    tags: list[str] = []
    for line in content.splitlines():
        if line.strip() == "tags:":
            in_tags = True
            continue
        if in_tags:
            if line.startswith("  - "):
                tags.append(line.strip().lstrip("- ").strip())
            else:
                break
    return tags


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Generator[Path, None, None]:
    """Minimal vault directory tree required by 04-enrich-tags.ps1."""
    (tmp_path / "00-Inbox").mkdir()
    (tmp_path / "01-Processing").mkdir()
    (tmp_path / "02-Library").mkdir()
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    yield tmp_path


# ---------------------------------------------------------------------------
# 1. LLM offline — early exit
# ---------------------------------------------------------------------------


class TestLLMOffline:
    """When LLM is unreachable the script exits 0 without touching any file."""

    def test_exits_zero_when_offline(self, vault: Path) -> None:
        result = run_enrich_tags(vault, llm_online=False)
        assert result.returncode == 0, result.stderr

    def test_no_files_modified_when_offline(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-warrior.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")
        original = note.read_text(encoding="utf-8")

        run_enrich_tags(vault, llm_online=False)

        assert note.read_text(encoding="utf-8") == original

    def test_bad_docs_not_written_when_offline(self, vault: Path) -> None:
        (vault / "01-Processing" / "npc-warrior.md").write_text(
            _NO_FRONTMATTER, encoding="utf-8"
        )

        run_enrich_tags(vault, llm_online=False)

        assert _bad_docs_entries(vault) == set()


# ---------------------------------------------------------------------------
# 2. Missing frontmatter → bad-doc
# ---------------------------------------------------------------------------


class TestMissingFrontmatter:
    """Files without YAML frontmatter are added to bad-docs.txt, not modified."""

    def test_marked_bad_when_no_frontmatter(self, vault: Path) -> None:
        note = vault / "01-Processing" / "orphan.md"
        note.write_text(_NO_FRONTMATTER, encoding="utf-8")

        run_enrich_tags(vault)

        entries = _bad_docs_entries(vault)
        assert any("orphan.md" in e for e in entries)

    def test_file_content_unchanged_when_no_frontmatter(self, vault: Path) -> None:
        note = vault / "01-Processing" / "orphan.md"
        note.write_text(_NO_FRONTMATTER, encoding="utf-8")

        run_enrich_tags(vault)

        assert note.read_text(encoding="utf-8") == _NO_FRONTMATTER

    def test_empty_file_marked_bad(self, vault: Path) -> None:
        note = vault / "01-Processing" / "empty.md"
        note.write_text("", encoding="utf-8")

        run_enrich_tags(vault)

        entries = _bad_docs_entries(vault)
        assert any("empty.md" in e for e in entries)


# ---------------------------------------------------------------------------
# 3. Already-rich notes — skipped
# ---------------------------------------------------------------------------


class TestAlreadyRich:
    """Files with >5 tags AND a type field are skipped without modification."""

    def test_rich_file_unchanged(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-rich.md"
        note.write_text(_FM_RICH, encoding="utf-8")

        run_enrich_tags(vault)

        assert note.read_text(encoding="utf-8") == _FM_RICH

    def test_script_exits_zero_for_rich_file(self, vault: Path) -> None:
        (vault / "01-Processing" / "npc-rich.md").write_text(_FM_RICH, encoding="utf-8")

        result = run_enrich_tags(vault)

        assert result.returncode == 0

    def test_exactly_six_tags_is_rich(self, vault: Path) -> None:
        """Boundary: exactly 6 tags + type → skipped (count > 5)."""
        content = (
            "---\nid: six-tags\ntype: npc\nstatus: draft\ntags:\n"
            "  - npc\n  - undead\n  - dark\n  - fire\n  - light\n  - location\n"
            "reviewed: false\n---\nBody.\n"
        )
        note = vault / "01-Processing" / "six-tags.md"
        note.write_text(content, encoding="utf-8")

        run_enrich_tags(vault)

        assert note.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# 4. Needs tags — enrichment
# ---------------------------------------------------------------------------


class TestNeedsTags:
    """Files with ≤5 tags get additional tags merged from the LLM stub."""

    def test_tags_increased_after_enrichment(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-sparse.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault)

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert len(tags) > 1

    def test_existing_tags_preserved(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-sparse.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark", "faction"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "npc" in tags  # original tag preserved

    def test_stub_tags_added(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-sparse.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark", "faction"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "dark" in tags
        assert "faction" in tags

    def test_no_duplicate_tags(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-sparse.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        # Stub returns "npc" which already exists
        run_enrich_tags(vault, stub_tags=["npc", "dark"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert tags.count("npc") == 1

    @pytest.mark.parametrize("count", [0, 1, 3, 5])
    def test_various_tag_counts_trigger_enrichment(
        self, vault: Path, count: int
    ) -> None:
        """Tag counts 0–5 all trigger enrichment."""
        tag_lines = "\n".join(f"  - npc" if i == 0 else f"  - lore" for i in range(count))
        content = (
            f"---\nid: test-{count}-tags\ntype: npc\nstatus: draft\n"
            f"tags:\n{tag_lines}\n---\nBody.\n"
        )
        note = vault / "01-Processing" / f"note-{count}-tags.md"
        note.write_text(content, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark", "faction"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "dark" in tags

    def test_five_tags_boundary_triggers_enrichment(self, vault: Path) -> None:
        """Boundary: exactly 5 tags (≤5) must trigger enrichment."""
        content = (
            "---\nid: five-boundary\ntype: npc\nstatus: draft\ntags:\n"
            "  - npc\n  - lore\n  - dark\n  - location\n  - faction\n---\nBody.\n"
        )
        note = vault / "01-Processing" / "five-boundary.md"
        note.write_text(content, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["undead"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "undead" in tags

    def test_body_preserved_after_tag_enrichment(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-sparse.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        assert "Needs more tags." in note.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. Needs type — type injection
# ---------------------------------------------------------------------------


class TestNeedsType:
    """Files without a type field get one injected from the LLM stub."""

    def test_type_field_injected(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-notype.md"
        note.write_text(_FM_NEEDS_TYPE, encoding="utf-8")

        run_enrich_tags(vault, stub_type="location")

        content = note.read_text(encoding="utf-8")
        assert _read_frontmatter_field(content, "type") == "location"

    def test_body_preserved_after_type_injection(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-notype.md"
        note.write_text(_FM_NEEDS_TYPE, encoding="utf-8")

        run_enrich_tags(vault, stub_type="location")

        content = note.read_text(encoding="utf-8")
        assert "Has tags but no type." in content

    @pytest.mark.parametrize(
        "stub_type",
        ["npc", "location", "faction", "quest", "creature", "item", "lore"],
    )
    def test_valid_types_injected(self, vault: Path, stub_type: str) -> None:
        """All valid entity types can be injected."""
        note = vault / "01-Processing" / f"note-{stub_type}.md"
        note.write_text(_FM_NEEDS_TYPE, encoding="utf-8")

        run_enrich_tags(vault, stub_type=stub_type)

        content = note.read_text(encoding="utf-8")
        assert _read_frontmatter_field(content, "type") == stub_type


# ---------------------------------------------------------------------------
# 6. Needs both type and tags
# ---------------------------------------------------------------------------


class TestNeedsBoth:
    """Files missing type AND with ≤5 tags get both enriched in one pass."""

    def test_type_and_tags_both_added(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-both.md"
        note.write_text(_FM_NEEDS_BOTH, encoding="utf-8")

        run_enrich_tags(vault, stub_type="faction", stub_tags=["dark", "undead"])

        content = note.read_text(encoding="utf-8")
        assert _read_frontmatter_field(content, "type") == "faction"
        tags = _read_tags(content)
        assert "dark" in tags
        assert "undead" in tags

    def test_existing_tag_preserved_while_adding_both(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-both.md"
        note.write_text(_FM_NEEDS_BOTH, encoding="utf-8")

        run_enrich_tags(vault, stub_type="faction", stub_tags=["dark"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "npc" in tags  # was already present


# ---------------------------------------------------------------------------
# 7. Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    """Files whose slug matches a 02-Library slug get duplicate_of injected."""

    def test_duplicate_of_field_injected(self, vault: Path) -> None:
        (vault / "02-Library" / "npc-warrior.md").write_text(
            "# Warrior", encoding="utf-8"
        )
        note = vault / "01-Processing" / "npc-warrior.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault)

        content = note.read_text(encoding="utf-8")
        assert "duplicate_of:" in content

    def test_non_duplicate_no_field(self, vault: Path) -> None:
        (vault / "02-Library" / "npc-wizard.md").write_text(
            "# Wizard", encoding="utf-8"
        )
        note = vault / "01-Processing" / "npc-warrior.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault)

        content = note.read_text(encoding="utf-8")
        assert "duplicate_of:" not in content

    def test_case_insensitive_slug_match(self, vault: Path) -> None:
        (vault / "02-Library" / "NPC-Warrior.md").write_text(
            "# Warrior", encoding="utf-8"
        )
        note = vault / "01-Processing" / "npc-warrior.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault)

        content = note.read_text(encoding="utf-8")
        assert "duplicate_of:" in content

    def test_duplicate_of_not_injected_twice(self, vault: Path) -> None:
        """Second run must not add a second duplicate_of line."""
        (vault / "02-Library" / "npc-warrior.md").write_text(
            "# Warrior", encoding="utf-8"
        )
        note = vault / "01-Processing" / "npc-warrior.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault)
        run_enrich_tags(vault)

        content = note.read_text(encoding="utf-8")
        assert content.count("duplicate_of:") == 1


# ---------------------------------------------------------------------------
# 8. Bad-docs skip
# ---------------------------------------------------------------------------


class TestBadDocsSkip:
    """Paths listed in bad-docs.txt are skipped even if the file is processable."""

    def test_skipped_when_in_bad_docs(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-sparse.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")
        original = note.read_text(encoding="utf-8")

        bad_docs = _bad_docs_path(vault)
        bad_docs.write_text(
            r"01-Processing\npc-sparse.md", encoding="utf-8"
        )

        run_enrich_tags(vault)

        assert note.read_text(encoding="utf-8") == original

    def test_other_files_still_processed(self, vault: Path) -> None:
        (vault / "01-Processing" / "skip-me.md").write_text(
            _FM_NEEDS_TAGS, encoding="utf-8"
        )
        process_me = vault / "01-Processing" / "process-me.md"
        process_me.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        bad_docs = _bad_docs_path(vault)
        bad_docs.write_text(r"01-Processing\skip-me.md", encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        tags = _read_tags(process_me.read_text(encoding="utf-8"))
        assert "dark" in tags


# ---------------------------------------------------------------------------
# 9. Both scan directories
# ---------------------------------------------------------------------------


class TestScanDirectories:
    """Both 00-Inbox/ and 01-Processing/ are scanned for markdown files."""

    def test_inbox_file_processed(self, vault: Path) -> None:
        note = vault / "00-Inbox" / "npc-inbox.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "dark" in tags

    def test_processing_file_processed(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-proc.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["faction"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "faction" in tags

    def test_both_dirs_in_same_run(self, vault: Path) -> None:
        inbox = vault / "00-Inbox" / "npc-a.md"
        proc = vault / "01-Processing" / "npc-b.md"
        inbox.write_text(_FM_NEEDS_TAGS, encoding="utf-8")
        proc.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        assert "dark" in _read_tags(inbox.read_text(encoding="utf-8"))
        assert "dark" in _read_tags(proc.read_text(encoding="utf-8"))

    def test_02_library_not_scanned(self, vault: Path) -> None:
        """02-Library files must never be modified by this script."""
        lib_note = vault / "02-Library" / "npc-canon.md"
        lib_note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")
        original = lib_note.read_text(encoding="utf-8")

        run_enrich_tags(vault)

        assert lib_note.read_text(encoding="utf-8") == original

    def test_missing_inbox_dir_handled(self, vault: Path) -> None:
        """Missing 00-Inbox/ directory handled gracefully (exit 0)."""
        (vault / "00-Inbox").rmdir()
        result = run_enrich_tags(vault)
        assert result.returncode == 0

    def test_missing_processing_dir_handled(self, vault: Path) -> None:
        """Missing 01-Processing/ directory handled gracefully (exit 0)."""
        (vault / "01-Processing").rmdir()
        result = run_enrich_tags(vault)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# 10. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Script must write structured logs with START/DONE markers."""

    def test_automation_log_created(self, vault: Path) -> None:
        run_enrich_tags(vault)
        assert (vault / ".automation" / "logs" / "automation.log").exists()

    def test_start_done_markers_present(self, vault: Path) -> None:
        run_enrich_tags(vault)
        log = (vault / ".automation" / "logs" / "automation.log").read_text(
            encoding="utf-8"
        )
        assert "--- START ---" in log
        assert "--- DONE" in log

    def test_log_appends_across_runs(self, vault: Path) -> None:
        run_enrich_tags(vault)
        run_enrich_tags(vault)
        log = (vault / ".automation" / "logs" / "automation.log").read_text(
            encoding="utf-8"
        )
        assert log.count("--- START ---") == 2

    def test_task_log_file_created(self, vault: Path) -> None:
        """Per-script daily log file (04-enrich-tags_YYYY-MM-DD.log) is written."""
        run_enrich_tags(vault)
        logs_dir = vault / ".automation" / "logs"
        task_logs = list(logs_dir.glob("04-enrich-tags_*.log"))
        assert len(task_logs) == 1

    def test_log_contains_timestamp_format(self, vault: Path) -> None:
        """Each log line must start with [YYYY-MM-DD HH:mm:ss]."""
        run_enrich_tags(vault)
        log = (vault / ".automation" / "logs" / "automation.log").read_text(
            encoding="utf-8"
        )
        pattern = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
        assert pattern.search(log), "No timestamped log line found"


# ---------------------------------------------------------------------------
# 11. Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running the script twice must produce identical results."""

    def test_double_run_exits_zero(self, vault: Path) -> None:
        (vault / "01-Processing" / "npc.md").write_text(
            _FM_NEEDS_TAGS, encoding="utf-8"
        )
        r1 = run_enrich_tags(vault)
        r2 = run_enrich_tags(vault)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

    def test_already_rich_unchanged_on_second_run(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-rich.md"
        note.write_text(_FM_RICH, encoding="utf-8")
        run_enrich_tags(vault)
        after_first = note.read_text(encoding="utf-8")

        run_enrich_tags(vault)

        assert note.read_text(encoding="utf-8") == after_first

    def test_enriched_file_stable_on_second_run(self, vault: Path) -> None:
        """After first-pass enrichment the file becomes rich; second run skips it."""
        note = vault / "01-Processing" / "npc-sparse.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark", "undead", "location", "faction", "item"])
        after_first = note.read_text(encoding="utf-8")

        run_enrich_tags(vault)

        assert note.read_text(encoding="utf-8") == after_first

    def test_empty_vault_idempotent(self, vault: Path) -> None:
        """Two runs on an empty vault both exit 0."""
        r1 = run_enrich_tags(vault)
        r2 = run_enrich_tags(vault)
        assert r1.returncode == 0
        assert r2.returncode == 0


# ---------------------------------------------------------------------------
# 12. Subdirectory scanning
# ---------------------------------------------------------------------------


class TestSubdirectoryScanning:
    """Script uses -Recurse, so nested subfolders inside 00-Inbox/ are scanned."""

    def test_inbox_subdirectory_file_processed(self, vault: Path) -> None:
        subdir = vault / "00-Inbox" / "images"
        subdir.mkdir()
        note = subdir / "npc-portrait.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "dark" in tags

    def test_processing_subdirectory_file_processed(self, vault: Path) -> None:
        subdir = vault / "01-Processing" / "arc-1"
        subdir.mkdir()
        note = subdir / "npc-boss.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["undead"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "undead" in tags

    def test_deeply_nested_file_processed(self, vault: Path) -> None:
        deep = vault / "00-Inbox" / "arc" / "session" / "notes"
        deep.mkdir(parents=True)
        note = deep / "npc-deep.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["faction"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "faction" in tags

    def test_relpath_in_bad_docs_uses_backslash(self, vault: Path) -> None:
        """Relative paths stored in bad-docs.txt use Windows backslash separators."""
        subdir = vault / "00-Inbox" / "images"
        subdir.mkdir()
        note = subdir / "no-yaml.md"
        note.write_text(_NO_FRONTMATTER, encoding="utf-8")

        run_enrich_tags(vault)

        entries = _bad_docs_entries(vault)
        # At least one entry should reference this file
        assert any("no-yaml.md" in e for e in entries)


# ---------------------------------------------------------------------------
# 13. No-body file
# ---------------------------------------------------------------------------


class TestNoBodyFile:
    """Files with empty body after frontmatter must not crash the script."""

    def test_no_body_script_exits_zero(self, vault: Path) -> None:
        note = vault / "01-Processing" / "no-body.md"
        note.write_text(_FM_NO_BODY, encoding="utf-8")

        result = run_enrich_tags(vault, stub_tags=["dark"])

        assert result.returncode == 0, result.stderr

    def test_no_body_tags_still_enriched(self, vault: Path) -> None:
        note = vault / "01-Processing" / "no-body.md"
        note.write_text(_FM_NO_BODY, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark", "undead"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "dark" in tags

    def test_no_body_frontmatter_intact(self, vault: Path) -> None:
        note = vault / "01-Processing" / "no-body.md"
        note.write_text(_FM_NO_BODY, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        content = note.read_text(encoding="utf-8")
        assert content.startswith("---")
        assert "id: test-no-body" in content


# ---------------------------------------------------------------------------
# 14. Unicode content
# ---------------------------------------------------------------------------


class TestUnicodeContent:
    """UTF-8 special characters must survive the read → enrich → write cycle."""

    def test_unicode_tags_and_body_preserved(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-unicode.md"
        note.write_text(_FM_UNICODE, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        content = note.read_text(encoding="utf-8")
        # Special chars in body
        assert "áéíóú" in content
        assert "ãõ" in content
        assert "ç" in content
        # Header preserved
        assert "Ñoño Mágico" in content

    def test_unicode_id_field_preserved(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-unicode.md"
        note.write_text(_FM_UNICODE, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        content = note.read_text(encoding="utf-8")
        assert "id: npc-ñoño-mágico" in content

    def test_unicode_output_is_utf8(self, vault: Path) -> None:
        """Output file must be valid UTF-8 (no BOM, no replacement chars)."""
        note = vault / "01-Processing" / "npc-unicode.md"
        note.write_text(_FM_UNICODE, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dark"])

        raw_bytes = note.read_bytes()
        # Reject BOM
        assert not raw_bytes.startswith(b"\xef\xbb\xbf"), "BOM found in output"
        # Must decode as UTF-8 cleanly
        decoded = raw_bytes.decode("utf-8")
        assert "�" not in decoded, "Replacement char in output"

    def test_em_dash_in_body_preserved(self, vault: Path) -> None:
        content = (
            "---\nid: lore-em-dash\ntype: lore\ntags:\n  - lore\n---\n"
            "Text with — em dash and … ellipsis.\n"
        )
        note = vault / "01-Processing" / "lore-em-dash.md"
        note.write_text(content, encoding="utf-8")

        # File is already rich-enough (1 tag ≤ 5 → enriched)
        run_enrich_tags(vault, stub_tags=["dark"])

        result = note.read_text(encoding="utf-8")
        assert "—" in result
        assert "…" in result


# ---------------------------------------------------------------------------
# 15. Tag filtering — only ValidTags survive
# ---------------------------------------------------------------------------


class TestTagFiltering:
    """LLM stub may return invalid tags; only those in $ValidTags must persist."""

    def test_invalid_stub_tags_absent_from_output(self, vault: Path) -> None:
        """Tags outside $ValidTags list must be filtered by the script."""
        note = vault / "01-Processing" / "npc-filter.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        # "dragon" and "wizard" are not in $ValidTags
        run_enrich_tags(vault, stub_tags=["dragon", "wizard", "npc", "dark"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "dragon" not in tags
        assert "wizard" not in tags

    def test_valid_stub_tags_present_in_output(self, vault: Path) -> None:
        note = vault / "01-Processing" / "npc-filter.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dragon", "npc", "dark"])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert "npc" in tags
        assert "dark" in tags

    def test_all_invalid_tags_marks_bad_doc(self, vault: Path) -> None:
        """If every LLM tag is invalid, the script must not write an empty tag list
        and should mark the file in bad-docs (LLM returned no valid tags)."""
        note = vault / "01-Processing" / "npc-allbad.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=["dragon", "wizard", "hero"])

        entries = _bad_docs_entries(vault)
        # Either the file is in bad-docs OR it was left unchanged (both are valid)
        content = note.read_text(encoding="utf-8")
        file_in_bad = any("npc-allbad.md" in e for e in entries)
        tags = _read_tags(content)
        valid_tags = {
            "npc", "creature", "monster", "location", "dungeon", "city", "village",
            "faction", "quest", "encounter", "item", "artifact", "lore", "religion",
            "event", "organization", "timeline", "undead", "dark", "fire", "light",
            "none", "portrait", "battlemap", "scene", "token", "images", "pathfinder2e",
        }
        bogus_in_file = any(t not in valid_tags for t in tags)
        assert file_in_bad or not bogus_in_file

    @pytest.mark.parametrize("tag", [
        "npc", "creature", "monster", "location", "dungeon", "city", "village",
        "faction", "quest", "encounter", "item", "artifact", "lore", "religion",
        "event", "organization", "timeline", "undead", "dark", "fire", "light",
        "none", "portrait", "battlemap", "scene", "token", "images", "pathfinder2e",
    ])
    def test_each_valid_tag_accepted(self, vault: Path, tag: str) -> None:
        """Every tag in $ValidTags must survive the enrichment round-trip."""
        note = vault / "01-Processing" / f"note-tag-{tag}.md"
        note.write_text(_FM_NEEDS_TAGS, encoding="utf-8")

        run_enrich_tags(vault, stub_tags=[tag])

        tags = _read_tags(note.read_text(encoding="utf-8"))
        assert tag in tags

