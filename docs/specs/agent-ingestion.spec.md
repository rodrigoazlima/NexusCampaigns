# Agent Spec — Ingestion

**Trigger:** hourly  
**Input:** `00-Inbox/` (all files recursively), `.agents/ingestion/state/processed-docx.txt`  
**Output:** `.shared/state/inbox-queue.json`, renamed files in `00-Inbox/`, converted `.md` files  
**Dispatch:** `claude-api` · `claude-haiku-4-5-20251001` · `tools_module: ingestion.tools.ingestion_agent`

---

## Responsibilities

1. **Emoji cleanup** — strip non-ASCII printable chars from filenames in `00-Inbox/`. Idempotent.
2. **DOCX conversion** — convert `.docx` files to GFM Markdown via `pandoc`. Extract embedded images to `00-Inbox/images/{slug}/`. Tracks converted files in `.system/processed-docx.txt`. Batch size: 10.
3. **Queue registration** — scan `00-Inbox/` for files not yet in `inbox-queue.json`; add entries with type and agent slots.

---

## Queue Entry Schema

```json
{
  "00-Inbox/images/A1/warrior.jpg": {
    "ingestedAt": "ISO-8601",
    "type": "image | document | other",
    "agents": {
      "vision": "pending | done | skip",
      "lore": "pending | done | skip",
      "classification": "pending | done | skip",
      "wiki": "pending | done | skip"
    }
  }
}
```

## Agent Slot Assignment by File Type

| File type | vision | lore | classification | wiki |
|-----------|--------|------|----------------|------|
| image     | pending | pending | pending | skip |
| document  | skip | skip | pending | pending |
| other     | skip | skip | skip | skip |

---

## Constraints

- Cannot call LLM
- Cannot modify `02-Library/`
- Cannot delete files from `00-Inbox/`
