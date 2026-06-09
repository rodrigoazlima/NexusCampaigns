# Agent Spec — Lore (`09-generate-npcs.ps1` → `09-generate-npcs.py`)

**Trigger:** hourly  
**Input:** images in `processed-images.json` with `type ∈ {portrait, body, token}` not yet in `processed-npcs.json`; `scenarios.json` for scenario context; `02-Library/` for canon reference  
**Output:** `01-Processing/{slug}-A{arc}.md` NPC sheets  
**Dependency:** LM Studio at `http://localhost:1234` with model `qwen3-vl-4b-instruct`

---

## Responsibilities

1. Load canon entities from `02-Library/` (frontmatter: id, type, tags, relationships).
2. For each eligible (image, scenario) pair: call vision LLM with NPC generation prompt.
3. Write AGENTS.md-compliant NPC markdown to `01-Processing/`.
4. Track processed pairs in `processed-npcs.json`.

---

## NPC Output Schema (frontmatter)

```yaml
id: npc-{slug}-A{arc}
type: npc
status: draft
quality: 0
name: string
ancestry: string
heritage: string
class: string
level: 1-20
str/dex/con/int/wis/cha: integer (-5 to +5)
abilities: [string, string, string]
trait/ideal/bond/flaw: string
role: string
relationships: ["[[entity-slug]]"]
source: [image-filename]
sha256: string
reviewed: false
```

---

## Constraints

- Cannot approve content
- Cannot modify `02-Library/`
- Cannot set `reviewed: true`
