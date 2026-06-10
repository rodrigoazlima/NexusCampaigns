"""Concrete FrontmatterIO — implements IFrontmatterIO.

Reads and writes YAML frontmatter in Markdown files.
Uses ruamel.yaml for round-trip fidelity when available; falls back to PyYAML.

Frontmatter block format:
    ---
    key: value
    ---
    body text
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from .interfaces import IFrontmatterIO

_FENCE_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)


# ---------------------------------------------------------------------------
# YAML helpers — ruamel first, PyYAML fallback
# ---------------------------------------------------------------------------

def _load_yaml(text: str) -> dict[str, Any]:
    try:
        from ruamel.yaml import YAML  # type: ignore[import]
        y = YAML()
        y.preserve_quotes = True
        result = y.load(text)
        return dict(result) if result else {}
    except ImportError:
        import yaml
        result = yaml.safe_load(text)
        return dict(result) if result else {}


def _dump_yaml(data: dict[str, Any]) -> str:
    try:
        from ruamel.yaml import YAML  # type: ignore[import]
        y = YAML()
        y.default_flow_style = False
        y.preserve_quotes    = True
        y.width              = 4096   # prevent line-wrapping
        buf = io.StringIO()
        y.dump(data, buf)
        return buf.getvalue()
    except ImportError:
        import yaml
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)


# ---------------------------------------------------------------------------
# FrontmatterIO
# ---------------------------------------------------------------------------

class FrontmatterIO(IFrontmatterIO):
    """Read and write YAML frontmatter blocks in Markdown files."""

    def read(self, path: Path) -> tuple[dict[str, Any], str]:
        content = path.read_text(encoding="utf-8")
        m = _FENCE_RE.match(content)
        if not m:
            return {}, content
        fm   = _load_yaml(m.group(1))
        body = content[m.end():]
        return fm, body

    def write(self, path: Path, frontmatter: dict[str, Any], body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        yaml_str = _dump_yaml(frontmatter).rstrip("\n")
        content  = f"---\n{yaml_str}\n---\n{body}"
        path.write_text(content, encoding="utf-8")
