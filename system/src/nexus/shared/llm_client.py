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
import re
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

_JSON_FENCE_RE = re.compile(r"^```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Unwrap a ```json ... ``` fence some models wrap JSON replies in.

    Only triggers when the reply *starts* with a fence, so a plain
    "not JSON at all" reply still reaches json.loads and raises
    LLMResponseError as before.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    m = _JSON_FENCE_RE.match(stripped)
    return m.group(1).strip() if m else stripped


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
            return json.loads(_strip_code_fence(raw))
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
                with urllib.request.urlopen(req, timeout=self._cfg.timeout_seconds) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    return result["choices"][0]["message"]["content"]

            except urllib.error.URLError as exc:
                raise LLMOfflineError(f"LLM server unreachable: {exc}") from exc

            except (TimeoutError, ConnectionError) as exc:
                # Read timeout / connection reset mid-response: server slow or
                # swapping models, not a bad image - must never mark the image
                # failed, so surface as offline (caller aborts batch, retries
                # next run).
                raise LLMOfflineError(f"LLM connection dropped: {exc}") from exc

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
