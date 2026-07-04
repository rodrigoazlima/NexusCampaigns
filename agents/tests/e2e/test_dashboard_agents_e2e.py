"""
E2E test: dashboard /agents page + /api/agents endpoint reflect registry.yaml.

Requires the dashboard dev server running (system/dashboard, `npm run dev`,
port 48080).

Run:
  pytest agents/tests/e2e/test_dashboard_agents_e2e.py -v -m e2e
"""
from __future__ import annotations

from pathlib import Path

import pytest
import requests
import yaml

pytestmark = pytest.mark.e2e

_AGENTS_DIR    = Path(__file__).resolve().parents[2]
_PROJECT_ROOT  = _AGENTS_DIR.parent
_REGISTRY_FILE = _AGENTS_DIR / "registry.yaml"

_DASHBOARD_BASE = "http://localhost:48080"


def _registry_agents() -> dict:
    raw = yaml.safe_load(_REGISTRY_FILE.read_text(encoding="utf-8"))
    return raw.get("agents", {})


def test_api_agents_lists_every_registry_agent():
    """GET /api/agents returns one entry per agents.* key in registry.yaml."""
    resp = requests.get(f"{_DASHBOARD_BASE}/api/agents", timeout=10)
    assert resp.status_code == 200, f"dashboard returned {resp.status_code}: {resp.text[:300]}"

    agents = resp.json()
    assert isinstance(agents, list) and agents, "expected non-empty agent list"

    got_names = {a["name"] for a in agents}
    expected_names = set(_registry_agents().keys())
    missing = expected_names - got_names
    assert not missing, f"agents missing from /api/agents: {sorted(missing)}"


def test_active_agents_report_a_status():
    """Every registry agent with status:active surfaces a real (non-planned) status."""
    resp = requests.get(f"{_DASHBOARD_BASE}/api/agents", timeout=10)
    assert resp.status_code == 200
    agents = {a["name"]: a for a in resp.json()}

    for key, reg_agent in _registry_agents().items():
        if reg_agent.get("status") != "active":
            continue
        info = agents.get(key)
        assert info is not None, f"active registry agent {key!r} missing from dashboard"
        assert info["status"] != "planned", f"agent {key!r} is active in registry but 'planned' on dashboard"


def test_agents_page_renders():
    """GET /agents (the HTML page) loads and lists each active agent's display name."""
    resp = requests.get(f"{_DASHBOARD_BASE}/agents", timeout=10)
    assert resp.status_code == 200, f"dashboard returned {resp.status_code}: {resp.text[:300]}"
    html = resp.text

    for key, reg_agent in _registry_agents().items():
        if reg_agent.get("status") != "active":
            continue
        assert key in html.lower() or reg_agent.get("task_id", "") in html, (
            f"active agent {key!r} not found on /agents page"
        )
