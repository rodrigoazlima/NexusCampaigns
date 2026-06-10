"""Shared pytest fixtures and sys.path bootstrap."""

import sys
from pathlib import Path

# Ensure .agents/ is on sys.path so `import shared` resolves
_AGENTS_DIR = Path(__file__).resolve().parents[1]
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))
