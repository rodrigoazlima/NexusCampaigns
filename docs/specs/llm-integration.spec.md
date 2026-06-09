# Spec — LLM Integration

---

## Endpoints

| Agent | Endpoint | Model | Purpose |
|-------|----------|-------|---------|
| Vision Agent | `http://localhost:1234/v1/chat/completions` | `qwen3-vl-4b-instruct` | Image classification (type/race/class/element/environment) |
| Lore Agent | `http://localhost:1234/v1/chat/completions` | `qwen3-vl-4b-instruct` | NPC sheet generation from image + scenario |
| Classification Agent | `http://localhost:8080/v1/chat/completions` | unspecified | Tag enrichment |

---

## Call Parameters

- `temperature: 0`
- `max_tokens: 350` (Vision), `700` (Lore)
- Up to 3 retries with 3s backoff
- Images resized to max 1024px on longest side before base64 encoding
- Connection errors (server offline) → skip batch, no permanent failure recorded

---

## Open Design Items

- Classification Agent uses separate port (8080) — consolidate to 1234 or document why separate.
- Face matching (`06-match-token.py`) Python script exists but no formal spec for distance threshold or match method.
