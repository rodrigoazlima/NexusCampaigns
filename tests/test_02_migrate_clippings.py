"""
Tests for .automation/legacy/02-migrate-clippings.ps1

Strategy: patch $VaultRoot + LLM endpoint URLs in script text, write to
tmp_path, spin up a local mock HTTP server, invoke via subprocess.

The script is idempotent: it reads *.md from Clippings/, asks a local LLM
to classify each file into one of (HR, SWE, AI, LIFE, MARKETING, SKILLS),
and moves the file to RAW/<CATEGORY>/. When the LLM endpoint is unreachable
it skips the entire batch (exit 0).

Behaviors under test:
  1. Category routing   -- file moved to correct RAW/<CATEGORY>/
  2. Empty inbox        -- exits 0, LLM never called
  3. LLM offline        -- exits 0, Clippings files untouched
  4. Bad category       -- unrecognized LLM reply defaults to SKILLS
  5. Collision          -- timestamp suffix when destination already exists
  6. Multi-file         -- all .md files processed in one pass
  7. Non-md ignored     -- only *.md files matched
  8. Content snippet    -- only first 600 chars sent to LLM
  9. Logging            -- START/DONE markers, move events recorded
  10. Idempotency       -- re-run on empty Clippings exits 0, no extra LLM calls
"""

from __future__ import annotations

import json
import re
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

SCRIPT_PATH = (
    Path(__file__).parent.parent / ".automation" / "legacy" / "02-migrate-clippings.ps1"
)
ORIGINAL_VAULT_ROOT = r"D:\Library\rpg\dm\pathway\knowledge-base"
ORIGINAL_LLM_BASE = "http://localhost:8080"

if not SCRIPT_PATH.exists():
    pytest.skip(
        f"Script not found (needs Task 2 adaptation): {SCRIPT_PATH}",
        allow_module_level=True,
    )

VALID_CATEGORIES = ("HR", "SWE", "AI", "LIFE", "MARKETING", "SKILLS")

_PS_EXE = "pwsh" if shutil.which("pwsh") else "powershell"


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
                self._send(
                    200,
                    {"choices": [{"message": {"content": state["category"]}}]},
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

    def set_category(self, category: str) -> None:
        """Set the category string the mock will return for the next call(s)."""
        self._state["category"] = category

    @property
    def calls(self) -> list[dict]:
        return self._state["calls"]

    @property
    def last_prompt(self) -> str | None:
        """Return the prompt text from the most recent LLM call, or None."""
        if not self._state["calls"]:
            return None
        return self._state["calls"][-1]["messages"][0]["content"]


@pytest.fixture()
def mock_llm() -> Generator[_LLMController, None, None]:
    """Spin up a thread-backed mock LLM HTTP server; yield controller; shut down."""
    state: dict = {"category": "AI", "calls": []}
    server = HTTPServer(("127.0.0.1", 0), _build_handler(state))
    port: int = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield _LLMController(port, state)
    finally:
        server.shutdown()


def _free_port() -> int:
    """Return a port number that is currently unbound (for offline simulation)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    # Socket released here; nothing will be listening on the returned port.


# ---------------------------------------------------------------------------
# Vault fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault(tmp_path: Path) -> Generator[Path, None, None]:
    """Create the minimal directory tree expected by 02-migrate-clippings.ps1."""
    (tmp_path / "Clippings").mkdir()
    for cat in VALID_CATEGORIES:
        (tmp_path / "RAW" / cat).mkdir(parents=True)
    (tmp_path / ".automation" / "logs").mkdir(parents=True)
    yield tmp_path


# ---------------------------------------------------------------------------
# Script runner
# ---------------------------------------------------------------------------


def run_migrate(
    vault_root: Path,
    llm_port: int,
) -> subprocess.CompletedProcess[str]:
    """
    Patch $VaultRoot and LLM endpoint URLs in the script, write to tmp_path,
    and execute via PowerShell.

    Pass *llm_port* pointing at a free (unbound) port to simulate LLM offline.
    """
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    mock_base = f"http://127.0.0.1:{llm_port}"

    patched = (
        script_text
        .replace(
            f"$VaultRoot   = '{ORIGINAL_VAULT_ROOT}'",
            f"$VaultRoot   = '{vault_root}'",
        )
        .replace(ORIGINAL_LLM_BASE, mock_base)
    )
    temp_script = vault_root / "_test-migrate-clippings.ps1"
    temp_script.write_text(patched, encoding="utf-8")

    return subprocess.run(
        [_PS_EXE, "-ExecutionPolicy", "Bypass", "-File", str(temp_script)],
        capture_output=True,
        text=True,
        timeout=90,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _log(vault: Path) -> str:
    return (vault / ".automation" / "logs" / "automation.log").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1. Category routing
# ---------------------------------------------------------------------------


class TestCategoryRouting:
    """Files moved to the correct RAW/<CATEGORY>/ subfolder."""

    @pytest.mark.parametrize("category", list(VALID_CATEGORIES))
    def test_routes_to_correct_folder(
        self, vault: Path, mock_llm: _LLMController, category: str
    ) -> None:
        """Each valid LLM reply routes the file into RAW/<CATEGORY>/."""
        mock_llm.set_category(category)
        src = vault / "Clippings" / "note.md"
        src.write_text("some content", encoding="utf-8")

        result = run_migrate(vault, mock_llm.port)

        assert result.returncode == 0, result.stderr
        assert (vault / "RAW" / category / "note.md").exists()
        assert not src.exists(), "Source must be removed from Clippings/"

    def test_content_preserved_after_move(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """File content is identical at the destination."""
        mock_llm.set_category("SWE")
        body = "# DDD Patterns\n\nAggregate roots and domain events."
        (vault / "Clippings" / "ddd.md").write_text(body, encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert (vault / "RAW" / "SWE" / "ddd.md").read_text(encoding="utf-8") == body

    def test_prompt_contains_title_and_snippet(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """LLM prompt includes the filename stem and content preview."""
        mock_llm.set_category("AI")
        (vault / "Clippings" / "llama-cpp-guide.md").write_text(
            "Local AI inference via llama.cpp.", encoding="utf-8"
        )

        run_migrate(vault, mock_llm.port)

        prompt = mock_llm.last_prompt
        assert prompt is not None
        assert "llama-cpp-guide" in prompt
        assert "Local AI inference" in prompt


# ---------------------------------------------------------------------------
# 2. Empty / missing inbox
# ---------------------------------------------------------------------------


class TestEmptyInbox:
    """Script exits cleanly and makes no LLM calls when there is nothing to do."""

    def test_empty_clippings_exits_ok(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        result = run_migrate(vault, mock_llm.port)

        assert result.returncode == 0
        assert mock_llm.calls == []

    def test_missing_clippings_exits_ok(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        (vault / "Clippings").rmdir()

        result = run_migrate(vault, mock_llm.port)

        assert result.returncode == 0

    def test_non_md_files_ignored(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Non-.md files in Clippings/ are not touched and trigger no LLM call."""
        clippings = vault / "Clippings"
        (clippings / "banner.png").write_bytes(b"\x89PNG")
        (clippings / "data.json").write_text("{}", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert (clippings / "banner.png").exists()
        assert (clippings / "data.json").exists()
        assert mock_llm.calls == []


# ---------------------------------------------------------------------------
# 3. LLM offline
# ---------------------------------------------------------------------------


class TestLLMOffline:
    """When the LLM endpoint is unreachable the batch is skipped (exit 0)."""

    def test_skips_batch_when_llm_offline(self, vault: Path) -> None:
        """Clippings files untouched; script exits 0."""
        src = vault / "Clippings" / "article.md"
        src.write_text("content", encoding="utf-8")

        # Point at a port with nothing listening.
        result = run_migrate(vault, llm_port=_free_port())

        assert result.returncode == 0
        assert src.exists(), "File must remain in Clippings/ when LLM is offline"

    def test_offline_logged(self, vault: Path) -> None:
        """Offline skip is recorded in the log file."""
        (vault / "Clippings" / "x.md").write_text("x", encoding="utf-8")

        run_migrate(vault, llm_port=_free_port())

        text = _log(vault)
        assert "offline" in text.lower() or "skipping" in text.lower()


# ---------------------------------------------------------------------------
# 4. Unrecognized / bad category defaults to SKILLS
# ---------------------------------------------------------------------------


class TestBadCategory:
    """Unrecognized LLM response causes the file to land in SKILLS."""

    @pytest.mark.parametrize(
        "bad_response",
        [
            "UNKNOWN",
            "RANDOM",
            "NONE",
            "N/A",
            "ERROR",
            "I dont know",
            "CATEGORY",
        ],
    )
    def test_defaults_to_skills(
        self,
        vault: Path,
        mock_llm: _LLMController,
        bad_response: str,
    ) -> None:
        """LLM reply that matches no valid category routes file to SKILLS."""
        mock_llm.set_category(bad_response)
        src = vault / "Clippings" / "mystery.md"
        src.write_text("unclear content", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert (vault / "RAW" / "SKILLS" / "mystery.md").exists()
        assert not src.exists()

    def test_fallback_recorded_in_log(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Log mentions the SKILLS fallback when category is unrecognized."""
        mock_llm.set_category("GARBAGE")
        (vault / "Clippings" / "test.md").write_text("x", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert "SKILLS" in _log(vault)


# ---------------------------------------------------------------------------
# 5. Collision handling
# ---------------------------------------------------------------------------


class TestCollisionHandling:
    """Timestamp suffix prevents overwriting an existing destination file."""

    def test_collision_adds_timestamped_copy(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """When dest file exists the incoming file gets a yyyyMMdd-HHmmss suffix."""
        mock_llm.set_category("AI")
        (vault / "Clippings" / "article.md").write_text("new content", encoding="utf-8")
        existing = vault / "RAW" / "AI" / "article.md"
        existing.write_text("old content", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        ai_dir = vault / "RAW" / "AI"
        timestamped = list(ai_dir.glob("article *.md"))
        assert len(timestamped) == 1, "Expected exactly one timestamped copy"
        assert timestamped[0].read_text(encoding="utf-8") == "new content"
        assert existing.read_text(encoding="utf-8") == "old content", "Original must be intact"

    def test_collision_filename_pattern(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Timestamped filename matches ``stem yyyyMMdd-HHmmss.md``."""
        mock_llm.set_category("HR")
        (vault / "Clippings" / "resume.md").write_text("cv", encoding="utf-8")
        (vault / "RAW" / "HR" / "resume.md").write_text("old", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        files = [f.name for f in (vault / "RAW" / "HR").glob("resume *.md")]
        assert files, "No timestamped file found"
        assert re.match(r"resume \d{8}-\d{6}\.md$", files[0]), (
            f"Unexpected filename format: {files[0]}"
        )

    def test_no_suffix_when_dest_is_free(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """No timestamp suffix when the destination path is clear."""
        mock_llm.set_category("LIFE")
        (vault / "Clippings" / "habits.md").write_text("atomic habits", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert (vault / "RAW" / "LIFE" / "habits.md").exists()
        assert not list((vault / "RAW" / "LIFE").glob("habits *.md"))


# ---------------------------------------------------------------------------
# 6. Multi-file processing
# ---------------------------------------------------------------------------


class TestMultiFile:
    """All .md files in Clippings/ are processed in a single script run."""

    def test_all_files_moved(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Three files → three LLM calls → three files moved, Clippings empty."""
        mock_llm.set_category("SWE")
        clippings = vault / "Clippings"
        names = ("alpha.md", "beta.md", "gamma.md")
        for name in names:
            (clippings / name).write_text(f"content of {name}", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert len(mock_llm.calls) == 3
        swe = vault / "RAW" / "SWE"
        for name in names:
            assert (swe / name).exists(), f"Expected {name} in RAW/SWE/"
            assert not (clippings / name).exists(), f"{name} must leave Clippings/"

    def test_each_file_gets_its_own_prompt(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Each file generates a separate LLM call with that file's title."""
        mock_llm.set_category("MARKETING")
        clippings = vault / "Clippings"
        (clippings / "growth-hacking.md").write_text("growth", encoding="utf-8")
        (clippings / "product-led.md").write_text("PLG", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        prompts = [call["messages"][0]["content"] for call in mock_llm.calls]
        titles_seen = {p for prompt in prompts for p in ["growth-hacking", "product-led"] if p in prompt}
        assert titles_seen == {"growth-hacking", "product-led"}


# ---------------------------------------------------------------------------
# 7. Content snippet (600-char limit)
# ---------------------------------------------------------------------------


class TestContentSnippet:
    """Only the first 600 chars of file content appear in the LLM prompt."""

    def test_content_truncated_at_600_chars(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Characters beyond position 600 must not appear in the prompt."""
        mock_llm.set_category("SWE")
        content = "x" * 600 + "BEYOND_LIMIT"
        (vault / "Clippings" / "long.md").write_text(content, encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert mock_llm.last_prompt is not None
        assert "BEYOND_LIMIT" not in mock_llm.last_prompt

    def test_short_content_sent_in_full(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Files shorter than 600 chars are sent without truncation."""
        mock_llm.set_category("MARKETING")
        body = "Short marketing blurb - far under the limit."
        (vault / "Clippings" / "blurb.md").write_text(body, encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        assert body in (mock_llm.last_prompt or "")

    def test_empty_file_does_not_crash(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Empty .md file is classified and moved without error."""
        mock_llm.set_category("SKILLS")
        (vault / "Clippings" / "empty.md").write_text("", encoding="utf-8")

        result = run_migrate(vault, mock_llm.port)

        assert result.returncode == 0
        assert (vault / "RAW" / "SKILLS" / "empty.md").exists()


# ---------------------------------------------------------------------------
# 8. Logging
# ---------------------------------------------------------------------------


class TestLogging:
    """Structured log written to .automation/logs/automation.log."""

    def test_log_file_created(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        run_migrate(vault, mock_llm.port)

        assert (vault / ".automation" / "logs" / "automation.log").exists()

    def test_log_has_start_and_done_markers(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        run_migrate(vault, mock_llm.port)

        text = _log(vault)
        assert "--- START ---" in text
        assert "--- DONE ---" in text

    def test_log_records_moved_file(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Log line mentions filename and destination category for each move."""
        mock_llm.set_category("AI")
        (vault / "Clippings" / "gpt-tips.md").write_text("AI", encoding="utf-8")

        run_migrate(vault, mock_llm.port)

        text = _log(vault)
        assert "gpt-tips.md" in text
        assert "AI" in text

    def test_log_appends_on_consecutive_runs(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """Each run appends to the log; START/DONE markers appear once per run."""
        run_migrate(vault, mock_llm.port)
        run_migrate(vault, mock_llm.port)

        text = _log(vault)
        assert text.count("--- START ---") == 2
        assert text.count("--- DONE ---") == 2


# ---------------------------------------------------------------------------
# 9. Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Re-running the script after files are moved is safe and makes no LLM calls."""

    def test_double_run_exits_ok(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        mock_llm.set_category("SKILLS")
        (vault / "Clippings" / "vim-tips.md").write_text("config", encoding="utf-8")

        r1 = run_migrate(vault, mock_llm.port)
        r2 = run_migrate(vault, mock_llm.port)

        assert r1.returncode == 0, f"Run 1 stderr: {r1.stderr}"
        assert r2.returncode == 0, f"Run 2 stderr: {r2.stderr}"

    def test_second_run_makes_no_llm_calls(
        self, vault: Path, mock_llm: _LLMController
    ) -> None:
        """After the first run Clippings/ is empty; second run skips LLM entirely."""
        mock_llm.set_category("HR")
        (vault / "Clippings" / "cv.md").write_text("resume", encoding="utf-8")

        run_migrate(vault, mock_llm.port)
        after_first = len(mock_llm.calls)

        run_migrate(vault, mock_llm.port)
        after_second = len(mock_llm.calls)

        assert after_first == 1
        assert after_second == 1, "Second run must not call LLM (Clippings is empty)"

