# Impl: Reflexion Loop — Lore Agent

**Phase:** P1  
**Priority:** High  
**Effort:** 2 days  
**Depends on:** nothing (uses existing QualityGate)

---

## Problem

The Lore Agent generates NPC sheets in a single LLM call with `temperature=0` and never inspects the result. Quality is bounded by the prompt, not by iteration. A generated NPC with `## Description\nA mysterious figure.` and one wikilink scores structural quality 6/10 and gets written as-is. No feedback loop exists.

---

## Goal

After generation, the Lore Agent scores its own output using `QualityGate`. If score < 7, it feeds specific gap information back into a second generation round. Maximum 2 revision rounds. If score is still < 7 after round 2, the output is written with `needs_human_review: true` added to frontmatter and a `## Reviewer Notes` section listing which quality dimensions failed.

---

## Scope

Files to modify:
- `.agents/lore/tools/generate_npcs.py` — add reflexion loop in `run_batch()`
- `.agents/lore/prompts/system.md` — add revision instruction section
- `.agents/shared/interfaces.py` — add `IReflexionContext` protocol (optional, if warranted)

Files to create:
- `.agents/lore/prompts/revise-npc.md` — revision prompt template
- `.agents/tests/test_reflexion.py` — unit tests for loop logic

---

## Implementation

### Step 1 — Score immediately after generation

In `generate_npcs.py`, inside `run_batch()`, after calling `self._generator.generate(...)`:

```python
from shared.quality_gate import QualityGate

_GATE = QualityGate()
_MAX_REVISIONS = 2

def _score_and_revise(
    self,
    image_path: Path,
    scenario: dict,
    canon_context: str,
    first_output: NPCLLMOutput,
) -> NPCLLMOutput:
    """Run up to _MAX_REVISIONS critique rounds. Return best output."""
    current = first_output
    fm = _output_to_frontmatter(current)
    body = _output_to_body(current)
    score = _GATE.score(fm, body)

    for round_num in range(1, _MAX_REVISIONS + 1):
        if score >= 7:
            break
        critique = _build_critique(fm, body, score)
        revised = self._generator.generate_with_critique(
            image_path, scenario, canon_context, critique
        )
        new_fm = _output_to_frontmatter(revised)
        new_body = _output_to_body(revised)
        new_score = _GATE.score(new_fm, new_body)
        if new_score > score:
            current, fm, body, score = revised, new_fm, new_body, new_score

    if score < 7:
        current = _flag_for_human_review(current, score)
    return current
```

### Step 2 — Build critique from gate dimensions

```python
def _build_critique(fm: dict, body: str, score: int) -> str:
    gaps = []
    if not re.search(r"^##\s+(description|descrição)", body, re.I | re.M):
        gaps.append("- Missing '## Description' section with meaningful content")
    rels = fm.get("relationships") or []
    if not rels and not re.findall(r"\[\[.+?\]\]", body):
        gaps.append("- No [[wikilinks]] to related entities (location, faction, quest)")
    if len(fm.get("tags") or []) < 3:
        gaps.append("- Fewer than 3 tags; add specific PF2e and campaign tags")
    if not fm.get("source"):
        gaps.append("- Missing source field")

    gap_text = "\n".join(gaps)
    return (
        f"The previous NPC sheet scored {score}/10. "
        f"It is missing these required elements:\n{gap_text}\n\n"
        f"Revise the NPC sheet to address all gaps above. "
        f"Keep all correct information from the previous version."
    )
```

### Step 3 — `generate_with_critique` on INPCGenerator

Add to `shared/interfaces.py`:

```python
class INPCGenerator(ABC):
    # existing generate() method stays

    @abstractmethod
    def generate_with_critique(
        self,
        image_path: Path,
        scenario: dict,
        canon_context: str,
        critique: str,
    ) -> NPCLLMOutput:
        """Re-generate with critique injected into user turn. Same contract as generate()."""
        ...
```

The concrete implementation in `lore/tools/` appends the critique as a `user` message after the previous failed output in the message history, then calls the LLM again.

### Step 4 — Flag unresolved outputs

```python
def _flag_for_human_review(output: NPCLLMOutput, score: int) -> NPCLLMOutput:
    output.needs_human_review = True
    output.review_notes = (
        f"Auto-generated. Quality score after {_MAX_REVISIONS} revision rounds: {score}/10. "
        f"Human review required before Library promotion."
    )
    return output
```

The writer adds to the generated markdown:

```markdown
## Reviewer Notes

> Auto-flagged: quality score {score}/10 after 2 revision rounds. Check: description depth, wikilinks, tags.
```

And sets frontmatter: `needs_human_review: true`.

---

## Revision Prompt Template (`.agents/lore/prompts/revise-npc.md`)

```
You previously generated an NPC sheet that did not meet quality standards.

CRITIQUE:
{critique}

ORIGINAL OUTPUT:
{original_output}

Produce a revised NPC sheet that fixes all listed issues.
Preserve any correct stat blocks, names, and lore from the original.
Return the same JSON structure as before.
```

---

## Lore Agent `system.md` Addition

Add to `## Rules` in `lore/prompts/system.md`:

```
- After generating each NPC, call `score_output` to check quality.
  If quality < 7, call `revise_npc` with the critique. Max 2 revisions.
  If still < 7 after 2 rounds, set needs_human_review: true in frontmatter.
```

---

## State Changes

No new state files. The reflexion loop is in-memory within a single `run_batch()` call. The processed-pair composite key `(image_sha256|scenario_id)` is written only after the final output (pass or flagged), same as before.

---

## Tests

`.agents/tests/test_reflexion.py`:

```python
def test_passes_on_first_try_if_score_7():
    # Mock generator returns quality-7 output
    # Verify generator called exactly once

def test_revises_once_on_low_score():
    # Mock: round 1 returns score 4, round 2 returns score 8
    # Verify generator called twice, final output is round-2 result

def test_flags_after_two_failed_rounds():
    # Mock: both rounds return score 4
    # Verify needs_human_review=True in output
    # Verify generator called exactly twice (not three times)

def test_keeps_best_score_if_revision_regresses():
    # Mock: round 1 score=6, round 2 score=3 (regression)
    # Verify final output is round-1 version (score 6)
    # Verify needs_human_review=True (still below threshold)
```

---

## Success Criteria

- NPC sheets that fail quality gate are revised before writing, not after.
- No revision round runs more than twice per item.
- Flagged items are human-identifiable via `needs_human_review: true` frontmatter.
- Lore agent metrics still track `itemsProcessed` and `itemsFailed` correctly.
- All existing lore agent tests still pass.
