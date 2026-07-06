"""Concrete StateStore implementations — satisfy IStateStore.

StateStore     — atomic JSON reads/writes via tmp-rename pattern.
TextStateStore — atomic newline-delimited plain-text state files (set[str]).
bootstrap_vault_state — idempotent one-call startup helper.

BOM-stripping on read covers Windows PowerShell UTF-8-BOM output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .interfaces import IStateStore


class StateStore(IStateStore):
    """Atomic JSON state file reader/writer."""

    def __init__(self, path: Path, default: Any) -> None:
        self._path    = path
        self._default = default

    def load(self) -> Any:
        if not self._path.exists():
            return (
                self._default.copy()
                if isinstance(self._default, (dict, list))
                else self._default
            )
        text = self._path.read_text(encoding="utf-8").lstrip("﻿")
        return json.loads(text)

    def save(self, data: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def update(self, updater: Callable[[Any], Any]) -> None:
        data   = self.load()
        result = updater(data)
        self.save(result if result is not None else data)

    def init_defaults(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self.save(self._default)


class TextStateStore(IStateStore):
    """Atomic state store for newline-delimited plain-text files.

    Used for processed-docx.txt, processed.txt, bad-wiki-docs.txt, bad-docs.txt.

    load()  → set[str] of non-empty stripped lines
    save()  → sorted lines with trailing newline (atomic tmp-rename)
    update() → load → apply updater(set[str]) → save
    init_defaults() → creates empty file if absent (idempotent)
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> set[str]:
        if not self._path.exists():
            return set()
        return {
            ln.strip()
            for ln in self._path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }

    def save(self, data: Any) -> None:  # data: set[str] | list[str] | iterable
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = sorted(data)
        content = "\n".join(lines) + "\n" if lines else ""
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(self._path)

    def update(self, updater: Callable[[set[str]], Any]) -> None:
        data   = self.load()
        result = updater(data)
        self.save(result if result is not None else data)

    def init_defaults(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("", encoding="utf-8")


def bootstrap_vault_state(project_root: Path) -> None:
    """Create all required state directories and initialize missing state files.

    Idempotent — never overwrites existing files. Call once on runner/agent
    startup to guarantee a consistent on-disk state before any agent runs.

    Covers:
      - All REQUIRED_DIRS (mkdir -p)
      - All JSON state files in STATE_FILE_DEFAULTS (via StateStore.init_defaults)
      - All plain-text state files in TEXT_STATE_FILES (via TextStateStore.init_defaults)
    """
    from .defaults import REQUIRED_DIRS, STATE_FILE_DEFAULTS, TEXT_STATE_FILES

    for rel in REQUIRED_DIRS:
        (project_root / rel).mkdir(parents=True, exist_ok=True)

    for rel_path, default in STATE_FILE_DEFAULTS.items():
        StateStore(project_root / rel_path, default).init_defaults()

    for rel_path in TEXT_STATE_FILES:
        TextStateStore(project_root / rel_path).init_defaults()
