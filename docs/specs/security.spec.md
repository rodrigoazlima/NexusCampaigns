# Spec — Security Constraints

---

## Rules

- No agent may self-approve content (`reviewed: true` — human-only).
- No agent may write to `02-Library/` without `reviewed: true` already set by human.
- No agent may delete files from `00-Inbox/` (source preservation).
- Breaking canon requires explicit human `git commit` with reason in message.
- API keys are stored in environment variables only — never in `agent.json`, `registry.yaml`, or any committed file.

---

## Quality Gate

Promotion to `02-Library/` requires **all three** conditions:

| Field | Required value |
|-------|---------------|
| `status` | `approved` |
| `quality` | `>= 7` |
| `reviewed` | `true` |

Agents may suggest quality scores but may never write `approved` or `true` for these fields.

---

## API Key Management

LLM provider keys are read from environment variables at dispatch time. Never store keys in config files.

| Provider | Env var |
|---|---|
| Anthropic (Claude) | `ANTHROPIC_API_KEY` |
| OpenAI / LM Studio / LocalRouter | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |

Local endpoints (LM Studio, LocalRouter) require `OPENAI_API_KEY` set to any non-empty value (e.g. `"lm-studio"`).

LLM endpoint URLs and model identifiers are configured in `registry.yaml` `llm_endpoints` — not env vars.

---

## VaultGuard

`IVaultGuard` (`.agents/shared/vault_guard.py`) enforces write protection at runtime:

- Raises `VaultWriteError` on any attempted write to `02-Library/` or `00-Inbox/` by agent code.
- All agent tools must call `guard.assert_writable(target)` before writing.
- All agent tools must call `guard.assert_not_inbox_delete(target)` before deleting.
