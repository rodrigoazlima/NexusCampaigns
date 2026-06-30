# Spec — Linking Rules

---

Every `02-Library/` entity must have ≥1 outbound `[[wikilink]]`. No orphan entities.

| Entity type | Required links |
|-------------|----------------|
| npc | location, faction, or quest |
| quest | NPC + location |
| location | NPC or faction |
| faction | NPC + location |
| item | quest or owner NPC |
| encounter | location + creature |

---

## Enforcement

- **Wikilink Agent** auto-inserts missing links into `## Related` sections.
- **Review Agent** flags orphans in daily report.

---

## Wikilink Syntax

Use `[[slug-name]]` — match exact filename without extension.

```markdown
## Related

- [[npc-necromancer-black-hollow]]
- [[faction-cult-of-undying]]
```
