# Shared pytest fixtures and sys.path bootstrap.
#
# `nexus.*` (runner, shared, tasks) resolves via the editable install
# (`pip install -e ".[test]"`). The single sys.path insert below exists only
# for the LLM agents still living under agents/ (e.g. `lore.tools.*`), which
# are not part of the installed package. vision now dispatches via its own
# externally-cloned container (agents/vision - see shared/runners/docker.py)
# and is no longer importable in-process here at all.
#
# Legacy numbered tests (test_01…test_15) predate the agents pipeline and
# skip at module level when their SCRIPT_PATH no longer exists.

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
VAULT_ROOT = _PROJECT_ROOT

_AGENTS_DIR = _PROJECT_ROOT / "agents"
if str(_AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR))
