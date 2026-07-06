"""OpenAICompatRunner tool-use loop: executes tool_calls via call_tool() until finish."""
from __future__ import annotations

import json
from unittest.mock import patch

from shared.runners.openai_compat import OpenAICompatRunner, _to_openai_tools


def test_to_openai_tools_converts_anthropic_schema():
    anthropic_tools = [{
        "name": "list_pending_images",
        "description": "List images",
        "input_schema": {"type": "object", "properties": {}},
    }]
    converted = _to_openai_tools(anthropic_tools)
    assert converted == [{
        "type": "function",
        "function": {
            "name": "list_pending_images",
            "description": "List images",
            "parameters": {"type": "object", "properties": {}},
        },
    }]


def _http_response(body: dict):
    class _Resp:
        def read(self):
            return json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def test_tool_use_loop_calls_tool_then_stops(tmp_path):
    import types
    fake_mod = types.ModuleType("fake_vision_tools")
    fake_mod.TOOLS = [{
        "name": "run_batch",
        "description": "Run batch",
        "input_schema": {"type": "object", "properties": {}},
    }]
    calls = []

    def call_tool(name, args, context):
        calls.append(name)
        return "processed 1 image"

    fake_mod.call_tool = call_tool

    responses = [
        {"choices": [{"message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "1", "type": "function",
                            "function": {"name": "run_batch", "arguments": "{}"}}],
        }}]},
        {"choices": [{"message": {"role": "assistant", "content": "done"}}]},
    ]

    def fake_urlopen(req, timeout=None):
        return _http_response(responses.pop(0))

    cfg = {
        "base_url": "http://localhost:1234/v1",
        "model": "test-model",
        "tools_module": "fake_vision_tools",
        "max_tool_rounds": 5,
    }
    context = {
        "project_root": str(tmp_path),
        "agent_dir": str(tmp_path),
        "agents_dir": str(tmp_path),
    }

    with patch.dict("sys.modules", {"fake_vision_tools": fake_mod}), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = OpenAICompatRunner().run(cfg, context)

    assert result.exit_code == 0
    assert calls == ["run_batch"]
