You are a senior Python architect and configuration expert.

**Task:**
Analyze the provided Python script and extract all relevant configuration settings into a clean, well-structured configuration system.

**Requirements:**

1. **Two-level configuration architecture:**
   - **Level 1: Global Shared Config** (`.system/config/global.json`)
     - Contains variables and settings that are shared across multiple scripts/agents.
     - Always loaded first.
   - **Level 2: Local Script Config** (`.system/config/<script_name>.json`)
     - Contains script-specific settings and overrides.
     - Always loaded after global config (can override global values).
     - Can be empty (`{}`) but must always exist.

2. **Output Format:**
   - You must output **two valid JSON objects** clearly labeled.
   - Use sensible, descriptive keys in `snake_case`.
   - Include meaningful `default` values for every setting.
   - Add a `"description"` field for each major setting when helpful.
   - Group related settings under logical sections if needed.

3. **What to Extract:**
   - Hardcoded paths (especially those derived from `__file__`)
   - Constants (BATCH_SIZE, thresholds, limits, etc.)
   - LLM settings (URL, model, provider, etc.)
   - File/directory references
   - Magic numbers and strings that are likely to change
   - Any environment-dependent behavior

4. **Rules:**
   - Prefer putting common things (project roots, LLM config, logging, shared directories) in **global**.
   - Put script-specific behavior (batch sizes, task-specific prompts, agent name, etc.) in **local**.
   - Make sure the JSONs contain good defaults so the script works even if the files are deleted.
   - Use clear, consistent naming.
   - Do not include code - only configuration.

---

**Script to analyze:**

# tests\test_llm_client.py
"""Tests for shared.llm_client.LLMClient."""

import base64
import json
import io
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import urllib.error

import pytest

from shared.config import LLMEndpointConfig
from shared.llm_client import LLMClient, _resize_and_encode
from shared.interfaces import LLMOfflineError, LLMResponseError


@pytest.fixture
def cfg():
    return LLMEndpointConfig(
        url      = "http://localhost:1234/v1/chat/completions",
        model    = "test-model",
        type     = "vision",
        provider = "lmstudio",
    )


@pytest.fixture
def client(cfg):
    return LLMClient(cfg)


def _make_response(content: str) -> bytes:
    """Build a minimal OpenAI-compatible response body."""
    return json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode("utf-8")


class TestLLMClientIsAvailable:
    def test_returns_true_on_success(self, client):
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert client.is_available() is True

    def test_returns_false_on_error(self, client):
        with patch("urllib.request.urlopen", side_effect=Exception("refused")):
            assert client.is_available() is False

    def test_probe_url_replaces_completions(self, client):
        calls = []

        def mock_urlopen(req, timeout=None):
            calls.append(req.full_url)
            raise Exception("stop")

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            client.is_available()

        assert calls[0].endswith("/v1/models")


class TestLLMClientChat:
    def test_returns_content_string(self, client):
        body = _make_response("Hello from LLM")

        class MockResp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("urllib.request.urlopen", return_value=MockResp()):
            result = client.chat([{"role": "user", "content": "hi"}], max_tokens=50)
        assert result == "Hello from LLM"

    def test_raises_llm_offline_on_url_error(self, client):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection refused")):
            with pytest.raises(LLMOfflineError):
                client.chat([], max_tokens=50)

    def test_raises_llm_response_error_after_retries(self, client):
        bad_body = json.dumps({"no_choices": []}).encode()

        class MockResp:
            def read(self): return bad_body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("urllib.request.urlopen", return_value=MockResp()):
            with patch("time.sleep"):
                with pytest.raises((LLMResponseError, KeyError, IndexError)):
                    client.chat([], max_tokens=50)

    def test_retries_on_key_error(self, client):
        call_count = [0]
        bad_body   = json.dumps({"bad": "structure"}).encode()
        good_body  = _make_response("OK")

        class MockResp:
            def __init__(self, body): self._body = body
            def read(self): return self._body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        responses = iter([bad_body, bad_body, good_body])

        def mock_urlopen(req, timeout=None):
            return MockResp(next(responses))

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with patch("time.sleep"):
                result = client.chat([], max_tokens=50)
        assert result == "OK"

    def test_payload_includes_temperature_zero(self, client):
        payloads = []
        body = _make_response("x")

        class MockResp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def capture(req, timeout=None):
            payloads.append(json.loads(req.data))
            return MockResp()

        with patch("urllib.request.urlopen", side_effect=capture):
            client.chat([], max_tokens=100)

        assert payloads[0]["temperature"] == 0
        assert payloads[0]["max_tokens"] == 100
        assert payloads[0]["model"] == "test-model"


class TestLLMClientChatJson:
    def test_parses_json_response(self, client):
        body = _make_response('{"type": "portrait", "ancestry": "elf"}')

        class MockResp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("urllib.request.urlopen", return_value=MockResp()):
            result = client.chat_json([], max_tokens=50)

        assert result["type"] == "portrait"
        assert result["ancestry"] == "elf"

    def test_raises_response_error_on_non_json(self, client):
        body = _make_response("This is not JSON at all!")

        class MockResp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("urllib.request.urlopen", return_value=MockResp()):
            with pytest.raises(LLMResponseError):
                client.chat_json([], max_tokens=50)


def _make_valid_png(tmp_path, name="img.png", size=(100, 100)) -> Path:
    """Create a real PIL-valid PNG image."""
    from PIL import Image
    path = tmp_path / name
    Image.new("RGB", size, color=(128, 64, 32)).save(path)
    return path


class TestLLMClientVisionChat:
    def test_sends_image_and_prompt(self, client, tmp_path):
        pytest.importorskip("PIL")
        img_path = _make_valid_png(tmp_path, "portrait.png")

        body = _make_response('{"type": "portrait"}')

        class MockResp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        payloads = []

        def capture(req, timeout=None):
            payloads.append(json.loads(req.data))
            return MockResp()

        with patch("urllib.request.urlopen", side_effect=capture):
            result = client.vision_chat(
                img_path,
                "Classify this image",
                system="You are a classifier",
                max_tokens=350,
            )

        assert result["type"] == "portrait"
        messages = payloads[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        user_content = messages[1]["content"]
        assert any(p.get("type") == "image_url" for p in user_content)
        assert any(p.get("type") == "text" for p in user_content)

    def test_image_encoded_as_base64_jpeg(self, client, tmp_path):
        pytest.importorskip("PIL")
        img_path = _make_valid_png(tmp_path, "enc.png")

        payloads = []
        body = _make_response('{"ok": true}')

        class MockResp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def capture(req, timeout=None):
            payloads.append(json.loads(req.data))
            return MockResp()

        with patch("urllib.request.urlopen", side_effect=capture):
            client.vision_chat(img_path, "p", system="s", max_tokens=10)

        user_msg = payloads[0]["messages"][1]["content"]
        img_part = next(p for p in user_msg if p["type"] == "image_url")
        assert img_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_system_prompt_injected(self, client, tmp_path):
        pytest.importorskip("PIL")
        img_path = _make_valid_png(tmp_path, "sys.png")
        body = _make_response('{"x": 1}')

        class MockResp:
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        payloads = []

        def capture(req, timeout=None):
            payloads.append(json.loads(req.data))
            return MockResp()

        with patch("urllib.request.urlopen", side_effect=capture):
            client.vision_chat(img_path, "prompt text", system="system text", max_tokens=50)

        system_msg = payloads[0]["messages"][0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == "system text"


class TestResizeAndEncode:
    def test_returns_base64_string(self, tmp_path):
        pytest.importorskip("PIL")
        path = _make_valid_png(tmp_path, "test.png")
        result = _resize_and_encode(path)
        assert isinstance(result, str)
        base64.b64decode(result)  # must be valid base64

    def test_with_pil_resize_large_image(self, tmp_path):
        pytest.importorskip("PIL")
        path = _make_valid_png(tmp_path, "big.png", size=(2000, 2000))
        result = _resize_and_encode(path)
        decoded = base64.b64decode(result)
        assert decoded[:2] == b"\xff\xd8"  # JPEG magic

    def test_small_image_not_upscaled(self, tmp_path):
        pytest.importorskip("PIL")
        path = _make_valid_png(tmp_path, "small.png", size=(50, 50))
        result = _resize_and_encode(path)
        assert isinstance(result, str)

    def test_without_pil_falls_back_to_raw(self, tmp_path):
        # Simulate PIL unavailable by patching the import
        from PIL import Image
        raw_png_path = tmp_path / "fallback.png"
        Image.new("RGB", (10, 10)).save(raw_png_path)
        raw = raw_png_path.read_bytes()

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("no PIL")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = _resize_and_encode(raw_png_path)

        decoded = base64.b64decode(result)
        assert decoded == raw


class TestLLMClientCatchAllException:
    def test_generic_exception_exhausts_retries(self, client):
        """The bare except Exception branch (lines 159-160) catches non-URL errors."""

        class MockResp:
            def read(self): raise ValueError("unexpected runtime error")
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("urllib.request.urlopen", return_value=MockResp()):
            with patch("time.sleep"):
                with pytest.raises(ValueError, match="unexpected runtime error"):
                    client.chat([], max_tokens=50)


class TestLLMClientRetryWithJsonDecodeError:
    def test_retries_on_invalid_server_json(self, client):
        """Test _post retry when server returns non-JSON body."""
        call_count = [0]
        good_body  = _make_response("final")

        class MockResp:
            def __init__(self, body): self._body = body
            def read(self): return self._body
            def __enter__(self): return self
            def __exit__(self, *a): pass

        bodies = iter([b"not json at all", b"still bad", good_body])

        def mock_urlopen(req, timeout=None):
            return MockResp(next(bodies))

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with patch("time.sleep") as mock_sleep:
                result = client.chat([], max_tokens=50)

        assert result == "final"
        assert mock_sleep.call_count == 2  # slept twice between 3 attempts


---


Now analyze the script and generate both configurations.

```

---

### Recommended Project Structure

```
NexusCampaigns/
├── .system/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```

### Bonus: Loader Code Suggestion (for `shared/config.py`)

You can later create a simple loader like this:

```python
from pathlib import Path
import json

def load_config(script_path: Path):
    project_root = Path(__file__).resolve().parents[2]  # adjust as needed
    
    # Global
    global_path = project_root / "config" / "global.json"
    global_cfg = json.loads(global_path.read_text()) if global_path.exists() else {}
    
    # Local
    script_name = script_path.stem
    local_path = project_root / "config" / f"{script_name}.json"
    local_cfg = json.loads(local_path.read_text()) if local_path.exists() else {}
    
    # Merge (local overrides global)
    config = {**global_cfg, **local_cfg}
    return config
```

