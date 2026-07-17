"""
Tests for .automation/03-compile-wiki.ps1

Strategy: patch $VaultRoot and LLM endpoint URLs in script text, write to
tmp_path, spin up a local mock HTTP server, invoke via subprocess.

The script reads *.md from 00-Inbox/, calls a local LLM to generate structured
DM entity drafts, and writes output to 01-Processing/. It loads existing
02-Library/ entities as context, tracks processed files in
.automation/processed.txt, and records rejected files in bad-wiki-docs.txt.

Behaviors under test:
  1. LLM offline        -- exits 0, no drafts created, log says "offline"
  2. Processed skip     -- files in processed.txt are not reprocessed
  3. Bad-docs skip      -- files in bad-wiki-docs.txt are skipped + logged
  4. Short content      -- < 100 chars -> marked processed, no LLM call
  5. HTML stripping     -- HTML tags stripped before sending to LLM
  6. Truncation         -- content > 6000 chars truncated in prompt
  7. Happy path         -- draft .md created in 01-Processing/
  8. Collision          -- existing draft gets date suffix
  9. Slug generation    -- whitespace collapsed in output filename
  10. Null LLM reply    -- file added to bad-wiki-docs.txt
  11. CONNECTION_ERROR  -- batch stops, remaining files untouched
  12. Library context   -- entity list from 02-Library/ included in prompt
  13. Logging           -- START/DONE markers, both log files created
  14. Multi-file        -- all .md files in 00-Inbox/ processed
  15. Idempotency       -- second run skips files already in processed.txt
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).parent.parent / ".automation" / "03-compile-wiki.ps1"
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"
ORIGINAL_LLM_BASE = "http://localhost:8080"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

MAX_CONTENT_CHARS = 6000

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"

# Minimal valid LLM response the script accepts and saves.
_SAMPLE_DRAFT = """\
---
id: npc-sample-entity
type: npc
status: draft
quality: 0
created: 2026-01-01
updated: 2026-01-01
tags:
  - npc
  - dark
source:
  - sample-note
reviewed: false
relationships:
  - "[[location-test-place]]"
---

## Description

A mysterious figure shrouded in darkness.

## Details

- Ancient and dangerous
- Commands undead minions

## Hooks

- The party encounters this NPC at midnight.
- A village elder begs the party to negotiate.

## Related

[[location-test-place]] [[faction-shadow-cult]]
"""


# ---------------------------------------------------------------------------
# Mock LLM HTTP server
# ---------------------------------------------------------------------------


def _build_handler(state: dict) -> type:
    """Return a request handler class that reads/writes *state*."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/models":
                self._send(200, {"data": [{"id": "auto"}]})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/v1/chat/completions":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                state["calls"].append(body)
                reply = state["reply"]
                if callable(reply):
                    reply = reply(body)
                self._send(
                    200,
                    {"choices": [{"message": {"content": reply}}]},
                )

        def _send(self, code: int, data: dict) -> None:
            payload = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args) -> None:  # noqa: ANN002
            pass  # suppress per-request noise in test output

    return _Handler


class _LLMController:
    """Test handle for a running mock LLM server."""

    def __init__(self, port: int, state: dict) -> None:
        self.port = port
        self._state = state

    def set_reply(self, reply: str) -> None:
        """Set the content the mock returns for chat completion calls."""
        self._state["reply"] = reply

    @property
    def calls(self) -> list[dict]:
        return self._state["calls"]

    @property
    def last_prompt(self) -> str | None:
        """Content string from the most recent LLM call, or None."""
        if not self._state["calls"]:
            return None
        return self._state["calls"][-1]["messages"][0]["content"]


@pytest.fixture()
def mock_llm() -> Generator[_LLMController, None, None]:
    """Spin up a thread-backed mock LLM HTTP server; yield controller; shut down."""
    state: dict = {"reply": _SAMPLE_DRAFT, "calls": []}
    server = HTTPServer(("127.0.0.1", 0), _build_handler(state))
    port: int = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield _LLMController(port, state)
    finally:
        server.shutdown()


def _free_port() -> int:
    """Return a port number with nothing listening (simulates offline LLM)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Vault fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Generator[Path, None, None]:
    """Create the minimal directory tree expected by 03-compile-wiki.ps1."""
    (tmp_path / "00-Inbox").mkdir()
    (tmp_path / "01-Processing").mkdir()
    (tmp_path / "02-Library").mkdir()
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    yield tmp_path


# ---------------------------------------------------------------------------
# Script runner
# ---------------------------------------------------------------------------


def run_compile_wiki(
    vault_root: Path,
    llm_port: int,
    *,
    completions_port: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Patch $VaultRoot and LLM URLs in the script, write to tmp_path,
    and execute via PowerShell.

    *llm_port* is used for the /v1/models preflight check.
    *completions_port* overrides the chat completions endpoint port; when
    omitted both endpoints share *llm_port*. Pass an unbound port as
    *completions_port* to simulate a mid-batch connection error without
    affecting the preflight check.
    """
    effective_completions_port = completions_port if completions_port is not None else llm_port

    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    patched = (
        script_text
        .replace(
            f"$VaultRoot    = '{ORIGINAL_VAULT_ROOT}'",
            f"$VaultRoot    = '{vault_root}'",
        )
        # Patch models preflight URL independently of completions URL.
        .replace(
            "'http://localhost:8080/v1/models'",
            f"'http://127.0.0.1:{llm_port}/v1/models'",
        )
        # Patch completions endpoint (may differ from models port).
        .replace(
            "'http://localhost:8080/v1/chat/completions'",
            f"'http://127.0.0.1:{effective_completions_port}/v1/chat/completions'",
        )
    )

    temp_script = vault_root / "_test-compile-wiki.ps1"
    temp_script.write_text(patched, encoding="utf-8")

    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(temp_script)],
        capture_output=True,
        text=True,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(vault: Path) -> str:
    """Read the shared automation log."""
    return (vault / ".automation" / "logs" / "automation.log").read_text(
        encoding="utf-8"
    )


def _inbox_note(vault: Path, name: str, content: str) -> Path:
    """Write a note into 00-Inbox/ and return its Path."""
    path = vault / "00-Inbox" / name
    path.write_text(content, encoding="utf-8")
    return path


def _processing_files(vault: Path) -> list[Path]:
    """Return .md files currently in 01-Processing/."""
    return list((vault / "01-Processing").glob("*.md"))


def _processed_entries(vault: Path) -> set[str]:
    """Return relative paths recorded in .automation/processed.txt."""
    log = vault / ".automation" / "processed.txt"
    if not log.exists():
        return set()
    return {line for line in log.read_text(encoding="utf-8").splitlines() if line}


def _bad_docs_entries(vault: Path) -> set[str]:
    """Return relative paths recorded in .automation/bad-wiki-docs.txt."""
    log = vault / ".automation" / "bad-wiki-docs.txt"
    if not log.exists():
        return set()
    return {line for line in log.read_text(encoding="utf-8").splitlines() if line}


# ---------------------------------------------------------------------------
# 1. LLM offline
# ---------------------------------------------------------------------------


class TestLLMOffline:
    """When the local router is unreachable the batch is skipped entirely."""

    def test_exits_zero_when_offline(self, vault: Path) -> None:
        """Script exits 0 even when LLM is unreachable."""
        _inbox_note(vault, "note.md", "x" * 200)
        result = run_compile_wiki(vault, _free_port())
        assert result.returncode == 0

    def test_no_drafts_created_when_offline(self, vault: Path) -> None:
        """No files written to 01-Processing/ when LLM is offline."""
        _inbox_note(vault, "note.md", "x" * 200)
        run_compile_wiki(vault, _free_port())
        assert _processing_files(vault) == []

    def test_offline_logged(self, vault: Path) -> None:
        """Offline skip is recorded in the automation log."""
        _inbox_note(vault, "note.md", "x" * 200)
        run_compile_wiki(vault, _free_port())
        text = _log(vault)
        assert "offline" in text.lower() or "skipping" in text.lower()

    def test_processed_log_not_updated_when_offline(self, vault: Path) -> None:
        """Files are not marked processed when the LLM is offline."""
        _inbox_note(vault, "note.md", "x" * 200)
        run_compile_wiki(vault, _free_port())
        assert _processed_entries(vault) == set()


# ---------------------------------------------------------------------------
# 2. Processed-log skip
# ---------------------------------------------------------------------------


class TestProcessedSkip:
    """Files listed in processed.txt are not reprocessed."""

    def test_skips_already_processed_file(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """File in processed.txt: no LLM call, no draft created."""
        _inbox_note(vault, "already-done.md", "x" * 200)
        (vault / ".automation" / "processed.txt").write_text(
            r"00-Inbox\already-done.md" + "\n", encoding="utf-8"
        )

        run_compile_wiki(vault, mock_llm.port)

        assert mock_llm.calls == []
        assert _processing_files(vault) == []

    def test_unprocessed_file_not_affected_by_processed_log(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """A new file is processed even when another file's entry is in processed.txt."""
        (vault / ".automation" / "processed.txt").write_text(
            r"00-Inbox\old.md" + "\n", encoding="utf-8"
        )
        _inbox_note(vault, "new.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert len(mock_llm.calls) == 1
        assert len(_processing_files(vault)) == 1


# ---------------------------------------------------------------------------
# 3. Bad-docs skip
# ---------------------------------------------------------------------------


class TestBadDocsSkip:
    """Files in bad-wiki-docs.txt are skipped and the skip is logged."""

    def test_skips_bad_doc(self, vault: Path, mock_llm: _LLMController) -> None:
        """File in bad-wiki-docs.txt: no LLM call, no draft created."""
        _inbox_note(vault, "broken.md", "x" * 200)
        (vault / ".automation" / "bad-wiki-docs.txt").write_text(
            r"00-Inbox\broken.md" + "\n", encoding="utf-8"
        )

        run_compile_wiki(vault, mock_llm.port)

        assert mock_llm.calls == []
        assert _processing_files(vault) == []

    def test_bad_doc_skip_logged(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Skipping a bad doc is written to the automation log."""
        _inbox_note(vault, "broken.md", "x" * 200)
        (vault / ".automation" / "bad-wiki-docs.txt").write_text(
            r"00-Inbox\broken.md" + "\n", encoding="utf-8"
        )

        run_compile_wiki(vault, mock_llm.port)

        log_text = _log(vault)
        assert "bad-doc" in log_text.lower() or "skipping" in log_text.lower()


# ---------------------------------------------------------------------------
# 4. Short content skip
# ---------------------------------------------------------------------------


class TestShortContentSkip:
    """Files with fewer than 100 chars are silently marked processed."""

    @pytest.mark.parametrize(
        "content",
        ["", "too short", "x" * 99],
    )
    def test_short_content_no_llm_call(
        self, vault: Path, mock_llm: _LLMController, content: str
    ) -> None:
        """Short/empty notes: no LLM call, no draft, recorded in processed.txt."""
        _inbox_note(vault, "short.md", content)

        run_compile_wiki(vault, mock_llm.port)

        assert mock_llm.calls == []
        assert _processing_files(vault) == []
        assert r"00-Inbox\short.md" in _processed_entries(vault)

    def test_exactly_100_chars_is_processed(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Content of exactly 100 chars is not rejected (threshold is strictly < 100)."""
        _inbox_note(vault, "border.md", "x" * 100)

        run_compile_wiki(vault, mock_llm.port)

        assert len(mock_llm.calls) == 1


# ---------------------------------------------------------------------------
# 5. HTML stripping
# ---------------------------------------------------------------------------


class TestHtmlStripping:
    """HTML markup is stripped before content is sent to the LLM."""

    def test_html_tags_removed_from_prompt(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Raw HTML tags must not appear in the LLM prompt."""
        html = (
            "<html><body><p>My DM note about the dungeon.</p>"
            "<style>body{color:red}</style>"
            "<script>alert(1)</script>"
            "</body></html>" + " " + "x" * 60
        )
        _inbox_note(vault, "htmlnote.md", html)

        run_compile_wiki(vault, mock_llm.port)

        prompt = mock_llm.last_prompt or ""
        assert "<p>" not in prompt
        assert "<style>" not in prompt
        assert "<script>" not in prompt

    def test_text_content_preserved_after_strip(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Visible text inside HTML tags is preserved in the LLM prompt."""
        body = "<p>Ancient dungeon beneath the mountain fortress.</p>" + "y" * 60
        _inbox_note(vault, "htmlnote2.md", body)

        run_compile_wiki(vault, mock_llm.port)

        assert "Ancient dungeon" in (mock_llm.last_prompt or "")

    def test_html_only_note_skipped_after_strip(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Note whose visible text is < 100 chars after stripping is skipped."""
        body = "<style>body{color:red}</style><script>x=1</script><p>short</p>"
        _inbox_note(vault, "empty-after-strip.md", body)

        run_compile_wiki(vault, mock_llm.port)

        assert mock_llm.calls == []
        assert _processing_files(vault) == []


# ---------------------------------------------------------------------------
# 6. Content truncation
# ---------------------------------------------------------------------------


class TestContentTruncation:
    """Content exceeding 6 000 chars is truncated before being sent to the LLM."""

    def test_beyond_6000_not_in_prompt(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Characters past position 6 000 must not appear in the LLM prompt."""
        body = "A" * MAX_CONTENT_CHARS + "BEYOND_LIMIT_MARKER"
        _inbox_note(vault, "long.md", body)

        run_compile_wiki(vault, mock_llm.port)

        assert "BEYOND_LIMIT_MARKER" not in (mock_llm.last_prompt or "")

    def test_truncation_marker_appended(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """A truncation notice is appended to the prompt when content is cut."""
        body = "B" * (MAX_CONTENT_CHARS + 500)
        _inbox_note(vault, "huge.md", body)

        run_compile_wiki(vault, mock_llm.port)

        assert "truncated" in (mock_llm.last_prompt or "").lower()

    def test_short_content_sent_in_full(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Content shorter than 6 000 chars is sent without a truncation marker."""
        body = "The lich awakens." + "Z" * 200
        _inbox_note(vault, "short.md", body)

        run_compile_wiki(vault, mock_llm.port)

        prompt = mock_llm.last_prompt or ""
        assert "The lich awakens." in prompt
        assert "truncated" not in prompt.lower()


# ---------------------------------------------------------------------------
# 7. Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Primary workflow: note -> LLM -> draft written to 01-Processing/."""

    def test_draft_created_in_processing(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """A draft .md file appears in 01-Processing/ after a successful run."""
        _inbox_note(vault, "Necromancer Lord.md", "x" * 200)

        result = run_compile_wiki(vault, mock_llm.port)

        assert result.returncode == 0
        assert len(_processing_files(vault)) == 1

    def test_draft_contains_llm_reply(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Draft file content matches what the mock LLM returned."""
        mock_llm.set_reply(_SAMPLE_DRAFT)
        _inbox_note(vault, "entity.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        draft = _processing_files(vault)[0]
        assert "npc-sample-entity" in draft.read_text(encoding="utf-8")

    def test_file_added_to_processed_log(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Successfully processed file is recorded in processed.txt."""
        _inbox_note(vault, "myentity.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert r"00-Inbox\myentity.md" in _processed_entries(vault)

    def test_prompt_includes_source_title(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Source file title appears in the LLM prompt."""
        _inbox_note(vault, "Dragon Cult Leader.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert "Dragon Cult Leader" in (mock_llm.last_prompt or "")

    def test_prompt_includes_note_content(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Note body content appears in the LLM prompt."""
        marker = "UNIQUE_MARKER_DRAGON_CULT_LORE_XYZ"
        _inbox_note(vault, "note.md", marker + "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert marker in (mock_llm.last_prompt or "")

    def test_prompt_contains_valid_entity_types(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """The LLM prompt includes the list of valid entity types."""
        _inbox_note(vault, "quest.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        prompt = mock_llm.last_prompt or ""
        for entity_type in ("npc", "faction", "location", "quest"):
            assert entity_type in prompt


# ---------------------------------------------------------------------------
# 8. Collision handling
# ---------------------------------------------------------------------------


class TestCollisionHandling:
    """When a draft already exists in 01-Processing/ a date suffix is added."""

    def test_collision_adds_date_suffix(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Second draft for same slug: date-suffix copy created alongside original."""
        _inbox_note(vault, "old-entity.md", "x" * 200)
        (vault / "01-Processing" / "old-entity.md").write_text(
            "existing draft", encoding="utf-8"
        )

        run_compile_wiki(vault, mock_llm.port)

        drafts = list((vault / "01-Processing").glob("old-entity*.md"))
        assert len(drafts) == 2, f"Expected 2 drafts, got: {[d.name for d in drafts]}"

    def test_original_draft_intact_after_collision(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Existing draft is not overwritten; its content is unchanged."""
        _inbox_note(vault, "old-entity.md", "x" * 200)
        original = "original draft content"
        (vault / "01-Processing" / "old-entity.md").write_text(
            original, encoding="utf-8"
        )

        run_compile_wiki(vault, mock_llm.port)

        assert (
            vault / "01-Processing" / "old-entity.md"
        ).read_text(encoding="utf-8") == original

    def test_no_suffix_when_dest_is_free(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """No date suffix when no existing draft exists for the slug."""
        _inbox_note(vault, "fresh-entity.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        drafts = _processing_files(vault)
        assert len(drafts) == 1
        assert drafts[0].name == "fresh-entity.md"


# ---------------------------------------------------------------------------
# 9. Slug generation
# ---------------------------------------------------------------------------


class TestSlugGeneration:
    """Get-WikiSlug collapses whitespace in the output draft filename."""

    @pytest.mark.parametrize(
        "filename,expected_stem",
        [
            ("normal-title.md", "normal-title"),
            ("Title With Spaces.md", "Title With Spaces"),
            ("Title  Double  Space.md", "Title Double Space"),
            ("  leading and trailing  .md", "leading and trailing"),
        ],
    )
    def test_slug_whitespace_normalized(
        self,
        vault: Path,
        mock_llm: _LLMController,
        filename: str,
        expected_stem: str,
    ) -> None:
        """Draft filename slug has whitespace collapsed and trimmed."""
        _inbox_note(vault, filename, "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        drafts = _processing_files(vault)
        assert len(drafts) == 1, f"Expected one draft, found: {[d.name for d in drafts]}"
        assert drafts[0].stem == expected_stem


# ---------------------------------------------------------------------------
# 10. Null / empty LLM reply -> bad-wiki-docs.txt
# ---------------------------------------------------------------------------


class TestNullLLMReply:
    """When the LLM returns an empty response the file goes to bad-wiki-docs.txt."""

    def test_empty_reply_adds_to_bad_docs(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Empty LLM reply: no draft created, file recorded in bad-wiki-docs.txt."""
        mock_llm.set_reply("")
        _inbox_note(vault, "rejected.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert _processing_files(vault) == []
        assert r"00-Inbox\rejected.md" in _bad_docs_entries(vault)

    def test_empty_reply_not_in_processed_log(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """File with empty LLM reply is not added to processed.txt."""
        mock_llm.set_reply("")
        _inbox_note(vault, "rejected.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert r"00-Inbox\rejected.md" not in _processed_entries(vault)

    def test_empty_reply_logged(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Log mentions the API rejection when the LLM returns empty."""
        mock_llm.set_reply("")
        _inbox_note(vault, "rejected.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        log_text = _log(vault)
        assert "rejected" in log_text.lower() or "bad-wiki" in log_text.lower()


# ---------------------------------------------------------------------------
# 11. CONNECTION_ERROR stops batch
# ---------------------------------------------------------------------------
#
# Strategy: preflight (/v1/models) points at the live mock server so the
# pre-flight check passes. The chat-completions endpoint is redirected to an
# unbound port so Invoke-RestMethod receives "Unable to connect" immediately,
# which matches the CONNECTION_ERROR pattern and stops the batch without
# the 120-second Invoke-RestMethod timeout.


class TestConnectionError:
    """Mid-batch connection loss stops processing; unprocessed files remain."""

    def test_exits_zero_on_connection_error(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Script exits 0 even when completions endpoint is unreachable."""
        _inbox_note(vault, "note.md", "x" * 200)

        result = run_compile_wiki(
            vault, mock_llm.port, completions_port=_free_port()
        )

        assert result.returncode == 0

    def test_no_drafts_created_after_connection_error(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """No drafts written when completions endpoint is unreachable."""
        _inbox_note(vault, "note.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port, completions_port=_free_port())

        assert _processing_files(vault) == []

    def test_connection_error_logged(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Connection loss is recorded in the automation log."""
        _inbox_note(vault, "note.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port, completions_port=_free_port())

        log_text = _log(vault)
        assert (
            "connection" in log_text.lower()
            or "stopping" in log_text.lower()
            or "failed" in log_text.lower()
        )

    def test_second_file_untouched_after_connection_error(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Files after the first connection-error file are not processed."""
        _inbox_note(vault, "aaa-first.md", "x" * 200)
        _inbox_note(vault, "zzz-second.md", "x" * 200)
        dead_port = _free_port()

        run_compile_wiki(vault, mock_llm.port, completions_port=dead_port)

        processed = _processed_entries(vault)
        assert r"00-Inbox\zzz-second.md" not in processed


# ---------------------------------------------------------------------------
# 12. Library context
# ---------------------------------------------------------------------------


class TestLibraryContext:
    """Existing 02-Library/ entities are loaded and included in the LLM prompt."""

    def test_library_entity_id_in_prompt(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Entity ids from 02-Library/ appear in the LLM prompt."""
        (vault / "02-Library" / "npc-dark-wizard.md").write_text(
            "---\nid: npc-dark-wizard\ntype: npc\n---\nOld dark wizard.\n",
            encoding="utf-8",
        )
        _inbox_note(vault, "new-note.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert "npc-dark-wizard" in (mock_llm.last_prompt or "")

    def test_library_entity_type_in_prompt(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Entity types from 02-Library/ appear in the LLM prompt."""
        (vault / "02-Library" / "loc-shadow-citadel.md").write_text(
            "---\nid: loc-shadow-citadel\ntype: location\n---\nA dark citadel.\n",
            encoding="utf-8",
        )
        _inbox_note(vault, "note.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert "location" in (mock_llm.last_prompt or "")

    def test_empty_library_no_context_section(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """No 'Existing canon entities' section in prompt when 02-Library/ is empty."""
        _inbox_note(vault, "note.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert "Existing canon entities" not in (mock_llm.last_prompt or "")

    def test_library_entity_without_id_fallback_to_basename(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Entity without an id field falls back to filename stem in the prompt."""
        (vault / "02-Library" / "orphan-faction.md").write_text(
            "---\ntype: faction\n---\nA hidden guild.\n",
            encoding="utf-8",
        )
        _inbox_note(vault, "note.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert "orphan-faction" in (mock_llm.last_prompt or "")


# ---------------------------------------------------------------------------
# 13. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Structured logs written to the shared log and a per-script daily log."""

    def test_shared_log_created(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """automation.log exists after a run."""
        run_compile_wiki(vault, mock_llm.port)
        assert (vault / ".automation" / "logs" / "automation.log").exists()

    def test_per_script_log_created(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """A daily per-task log file (03-compile-wiki_YYYY-MM-DD.log) is written."""
        run_compile_wiki(vault, mock_llm.port)
        task_logs = list(
            (vault / ".automation" / "logs").glob("03-compile-wiki_*.log")
        )
        assert len(task_logs) == 1

    def test_log_has_start_and_done_markers(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Both --- START --- and --- DONE markers appear in the shared log."""
        run_compile_wiki(vault, mock_llm.port)
        text = _log(vault)
        assert "--- START ---" in text
        assert "--- DONE" in text

    def test_log_records_created_draft(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Log line mentions the draft filename after creation."""
        _inbox_note(vault, "dragon-hoard.md", "x" * 200)
        run_compile_wiki(vault, mock_llm.port)
        assert "dragon-hoard" in _log(vault)

    def test_log_appends_across_runs(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Consecutive runs append to the shared log; each has its own markers."""
        run_compile_wiki(vault, mock_llm.port)
        run_compile_wiki(vault, mock_llm.port)
        text = _log(vault)
        assert text.count("--- START ---") == 2
        assert text.count("--- DONE") == 2


# ---------------------------------------------------------------------------
# 14. Multi-file processing
# ---------------------------------------------------------------------------


class TestMultiFile:
    """All .md files in 00-Inbox/ are processed in a single script run."""

    def test_all_files_processed(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Three inbox notes -> three LLM calls -> three drafts."""
        for name in ("alpha.md", "beta.md", "gamma.md"):
            _inbox_note(vault, name, "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        assert len(mock_llm.calls) == 3
        assert len(_processing_files(vault)) == 3

    def test_all_files_in_processed_log(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Every processed file appears in processed.txt."""
        names = ("alpha.md", "beta.md")
        for name in names:
            _inbox_note(vault, name, "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        entries = _processed_entries(vault)
        for name in names:
            assert rf"00-Inbox\{name}" in entries

    def test_each_file_gets_its_own_prompt(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Each file generates a separate LLM call mentioning that file's title."""
        for name in ("lich-king.md", "shadow-guild.md"):
            _inbox_note(vault, name, "x" * 200)

        run_compile_wiki(vault, mock_llm.port)

        prompts = [c["messages"][0]["content"] for c in mock_llm.calls]
        seen = {t for p in prompts for t in ("lich-king", "shadow-guild") if t in p}
        assert seen == {"lich-king", "shadow-guild"}

    def test_non_md_files_ignored(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Non-.md files in 00-Inbox/ are never passed to the LLM."""
        (vault / "00-Inbox" / "portrait.png").write_bytes(b"\x89PNG\r\n")
        (vault / "00-Inbox" / "data.json").write_text("{}", encoding="utf-8")

        run_compile_wiki(vault, mock_llm.port)

        assert mock_llm.calls == []


# ---------------------------------------------------------------------------
# 15. Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Re-running after processing is safe and skips already-processed files."""

    def test_double_run_exits_ok(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Two consecutive runs both exit 0."""
        _inbox_note(vault, "entity.md", "x" * 200)

        r1 = run_compile_wiki(vault, mock_llm.port)
        r2 = run_compile_wiki(vault, mock_llm.port)

        assert r1.returncode == 0, f"Run 1: {r1.stderr}"
        assert r2.returncode == 0, f"Run 2: {r2.stderr}"

    def test_second_run_makes_no_llm_calls(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Second run skips files already in processed.txt - zero extra LLM calls."""
        _inbox_note(vault, "entity.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)
        after_first = len(mock_llm.calls)

        run_compile_wiki(vault, mock_llm.port)
        after_second = len(mock_llm.calls)

        assert after_first == 1
        assert after_second == 1, "Second run must not call LLM (file already processed)"

    def test_second_run_creates_no_extra_drafts(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """01-Processing/ has the same number of drafts after both runs."""
        _inbox_note(vault, "entity.md", "x" * 200)

        run_compile_wiki(vault, mock_llm.port)
        count_after_first = len(_processing_files(vault))

        run_compile_wiki(vault, mock_llm.port)
        count_after_second = len(_processing_files(vault))

        assert count_after_first == count_after_second

