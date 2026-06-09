# Agent Spec — Wiki (`03-compile-wiki.ps1`)

**Trigger:** hourly  
**Input:** `00-Inbox/` markdown notes  
**Output:** synthesized entity pages in `01-Processing/`

---

## Responsibilities

Synthesize entity pages from raw `00-Inbox/` markdown notes into structured drafts in `01-Processing/`.

---

## Constraints

- Cannot approve content
- Cannot modify `02-Library/`

---

## Open Design Item

Cross-link generation for `04-Relationships/` is described but implementation scope is partial. See `SDD.md` open items.
