"""Concrete StateStore — implements IStateStore.

Atomic JSON reads/writes via tmp-rename pattern.
One StateStore instance per state file.

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
