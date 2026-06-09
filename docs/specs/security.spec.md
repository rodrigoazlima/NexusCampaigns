# Spec — Security Constraints

---

## Rules

- No agent may self-approve content (`reviewed: true` — human-only).
- No agent may write to `02-Library/` without `reviewed: true` already set by human.
- No agent may delete files from `00-Inbox/` (source preservation).
- Breaking canon requires explicit human `git commit` with reason in message.
- LLM endpoints are localhost-only; no external API keys required.

---

## Quality Gate

Promotion to `02-Library/` requires **all three** conditions:

| Field | Required value |
|-------|---------------|
| `status` | `approved` |
| `quality` | `>= 7` |
| `reviewed` | `true` |

Agents may suggest quality scores but may never write `approved` or `true` for these fields.
