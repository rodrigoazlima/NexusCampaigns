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

# shared\llm_client.py
"""Concrete LLMClient - implements ILLMClient.

Sends requests to a local OpenAI-compatible endpoint.
  - temperature = 0
  - max 3 retries with 3 s backoff per llm-integration.spec.md
  - images resized to max 1024 px on longest side (JPEG 85%) before base64
  - URLError (server offline) → LLMOfflineError  (not a permanent failure)
  - bad response after all retries → LLMResponseError
"""

from __future__ import annotations

import base64
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import LLMEndpointConfig
from .interfaces import ILLMClient, LLMOfflineError, LLMResponseError

_MAX_RETRIES   = 3
_RETRY_DELAY_S = 3.0
_MAX_IMAGE_PX  = 1024


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _resize_and_encode(path: Path) -> str:
    """Resize image to max _MAX_IMAGE_PX on longest side, return base64 JPEG."""
    try:
        from PIL import Image  # type: ignore[import]

        img = Image.open(path).convert("RGB")
        w, h   = img.size
        scale  = min(_MAX_IMAGE_PX / max(w, h, 1), 1.0)
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        raw = buf.getvalue()
    except ImportError:
        raw = path.read_bytes()   # PIL unavailable - send raw bytes

    return base64.b64encode(raw).decode()


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class LLMClient(ILLMClient):
    """HTTP client for a local OpenAI-compatible LLM endpoint."""

    def __init__(self, cfg: LLMEndpointConfig) -> None:
        self._cfg = cfg

    # ------------------------------------------------------------------
    # ILLMClient
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        probe = self._cfg.url.replace("/v1/chat/completions", "/v1/models")
        try:
            req = urllib.request.Request(probe, method="GET")
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
    ) -> str:
        payload = {
            "model":       self._cfg.model,
            "messages":    messages,
            "temperature": 0,
            "max_tokens":  max_tokens,
        }
        return self._post(payload)

    def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
    ) -> dict[str, Any]:
        raw = self.chat(messages, max_tokens=max_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"Non-JSON LLM response: {raw[:300]}"
            ) from exc

    def vision_chat(
        self,
        image_path: Path,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        b64 = _resize_and_encode(image_path)
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {
                        "type":      "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ]
        return self.chat_json(messages, max_tokens=max_tokens)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> str:
        body     = json.dumps(payload).encode("utf-8")
        last_exc: Exception = RuntimeError("no attempts made")

        for attempt in range(_MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    self._cfg.url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    return result["choices"][0]["message"]["content"]

            except urllib.error.URLError as exc:
                raise LLMOfflineError(f"LLM server unreachable: {exc}") from exc

            except (KeyError, IndexError) as exc:
                last_exc = LLMResponseError(
                    f"Unexpected response structure (attempt {attempt + 1}): {exc}"
                )
            except json.JSONDecodeError as exc:
                last_exc = LLMResponseError(
                    f"Non-JSON response (attempt {attempt + 1}): {exc}"
                )
            except Exception as exc:
                last_exc = exc

            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_S)

        raise last_exc


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

