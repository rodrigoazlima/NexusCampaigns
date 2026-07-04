# Impl: Semantic Quality Scoring (LLM-as-Judge)

**Phase:** P5  
**Priority:** Medium  
**Effort:** 2 days  
**Depends on:** Cost tracking (P1) — HARD GATE. Do not implement without per-task cost logging.

---

## Problem

`QualityGate` (`shared/quality_gate.py`) scores on structural presence:
- `## Description` heading exists? +2
- `[[wikilink]]` present? +2
- ≥3 tags? +2
- `type` field set? +2
- `source` field set? +2

This catches missing structure but not shallow content. An NPC with `## Description\nHe is a man.` and one wikilink scores 6/10. A rich NPC with deep lore but no `source` field scores 8/10.

The structural gate is fast, deterministic, and free. It should remain the primary gate. The LLM judge is an optional second pass for entities that pass structural scoring but may still have poor content.

---

## Goal

An optional second scoring pass — `SemanticQualityJudge` — uses an LLM to evaluate content quality on a 1–10 scale with a structured critique. It runs ONLY on entities that:
1. Pass structural QualityGate with score ≥ 6
2. Are in the Curator pipeline (not in the reflexion loop — that has its own budget)
3. Have a per-task `enable_semantic_scoring: true` flag in `agent.json`

Cost gate: `max_tokens_per_run` must be set in `agent.json` before enabling.

---

## Scope

Files to create:
- `agents/shared/semantic_judge.py` — `SemanticQualityJudge` class
- `agents/shared/interfaces.py` — `ISemanticJudge` protocol (add)
- `agents/tests/test_semantic_judge.py`

Files to modify:
- `agents/curator/tools/curator_agent.py` — optionally call judge in `score_draft()`
- `agents/curator/agent.json` — add `enable_semantic_scoring` flag

---

## Interface

Add to `shared/interfaces.py`:

```python
@dataclass
class SemanticScore:
    score: int              # 1–10 LLM-assigned
    confidence: str         # "high" | "medium" | "low"
    critique: str           # 1-2 sentence summary of quality issues
    strong_points: list[str]
    weak_points: list[str]

class ISemanticJudge(ABC):
    @abstractmethod
    def judge(
        self,
        entity_type: str,
        title: str,
        body: str,
        context: str = "",     # optional: campaign context for grounding
    ) -> SemanticScore:
        """Score entity content on 1-10. Raises LLMOfflineError if unavailable."""
        ...
```

---

## `SemanticQualityJudge` Implementation

```python
class SemanticQualityJudge(ISemanticJudge):

    _SYSTEM = """You are a Dungeon Master quality reviewer.
Score the following {entity_type} entry for quality as campaign material.

Scoring criteria (each 0–2 points, max 10):
- Specificity: concrete details, not vague descriptions
- Usefulness: DM can use this at the table without modification
- Lore depth: fits a coherent world, has history or motivation
- Distinctiveness: memorable, not generic fantasy tropes
- Relationships: implies connections to other story elements

Return ONLY valid JSON:
{"score": <int 1-10>, "confidence": "<high|medium|low>",
 "critique": "<1-2 sentences>",
 "strong_points": ["..."], "weak_points": ["..."]}"""

    def __init__(self, llm_client: ILLMClient) -> None:
        self._llm = llm_client

    def judge(
        self,
        entity_type: str,
        title: str,
        body: str,
        context: str = "",
    ) -> SemanticScore:
        system = self._SYSTEM.format(entity_type=entity_type)
        user_parts = [f"Title: {title}\n\n{body}"]
        if context:
            user_parts.insert(0, f"Campaign context:\n{context}\n\n---\n\n")

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": "".join(user_parts)},
        ]
        result = self._llm.chat_json(messages, max_tokens=512)

        return SemanticScore(
            score         = int(result.get("score", 5)),
            confidence    = result.get("confidence", "low"),
            critique      = result.get("critique", ""),
            strong_points = result.get("strong_points", []),
            weak_points   = result.get("weak_points", []),
        )
```

Temperature is always 0 (from `LLMClient` contract). Judge is deterministic across runs.

---

## Curator Integration

In `curator/tools/curator_agent.py`, `score_draft()`:

```python
def score_draft(self, path: str) -> ScoringResult:
    # Step 1: structural gate (always)
    fm, body = self._frontmatter_io.read(Path(path))
    struct_score = self._quality_gate.score(fm, body)
    is_promotable = struct_score >= 7

    semantic: Optional[SemanticScore] = None
    combined_score = struct_score

    # Step 2: semantic judge (optional, gated)
    if self._cfg.enable_semantic_scoring and struct_score >= 6:
        try:
            semantic = self._judge.judge(
                entity_type = fm.get("type", "entity"),
                title       = Path(path).stem,
                body        = body,
            )
            # Combined score: weighted average (structural 60%, semantic 40%)
            combined_score = round(struct_score * 0.6 + semantic.score * 0.4)
            is_promotable  = combined_score >= 7
        except LLMOfflineError:
            # Semantic judge unavailable — fall back to structural only
            pass

    return ScoringResult(
        path         = path,
        score        = combined_score,
        struct_score = struct_score,
        semantic     = semantic,
        is_promotable = is_promotable,
        missing      = _compute_missing(fm, body, struct_score),
    )
```

---

## Curator `agent.json` Extension

```json
{
  "tasks": {
    "curator-agent": {
      "intervalSeconds": 3600,
      "description": "Score 01-Processing drafts; promote qualifying to 02-Library/",
      "dispatch": {
        "type": "claude-api",
        "claude_api": {
          "model": "claude-sonnet-4-6",
          "system_file": "prompts/system.md",
          "tools_module": "curator.tools.curator_agent",
          "history_file": "curator-agent-history.json",
          "max_tokens": 2048,
          "max_tokens_per_run": 100000,
          "enable_semantic_scoring": false,
          "timeout_seconds": 300,
          "max_tool_rounds": 25
        }
      }
    }
  }
}
```

`enable_semantic_scoring: false` by default. Human enables explicitly after reviewing cost data.

`max_tokens_per_run` must be set before `enable_semantic_scoring` can be turned on (enforced by a startup assertion in curator init).

---

## Curator Notes with Semantic Feedback

When semantic scoring is enabled and finds issues, `curator_notes` in frontmatter includes semantic critique:

```yaml
curator_notes: "Structural score: 8/10. Semantic score: 4/10 (combined: 6/10). Critique: NPC lacks distinctive motivation; role in the story is unclear. Weak: generic backstory, no clear conflict hook."
```

This gives the human DM specific content feedback, not just structural feedback.

---

## Cost Estimation

Semantic judge call per entity (Sonnet):
- Input: ~500 tokens (system + entity body)
- Output: ~150 tokens (JSON score)
- Cost per entity: ~$0.004 at Sonnet pricing

At 20 new drafts per day: ~$0.08/day. Low. Enable confidently once cost tracking is live.

At 200 drafts per day: ~$0.80/day. Still acceptable. Monitor via cost dashboard.

---

## Fallback Behavior

If `LLMOfflineError`: skip semantic scoring, use structural score only. Curator continues processing other drafts. No error state.

If LLM returns non-JSON or malformed response: log warning, skip semantic score, use structural. Never block promotion due to judge failure.

---

## Tests

`agents/tests/test_semantic_judge.py`:

```python
def test_returns_semantic_score_on_valid_response():
    # Mock LLM returns valid JSON score
    # Assert: SemanticScore.score set correctly

def test_falls_back_on_llm_offline():
    # Mock LLM raises LLMOfflineError
    # Assert: SemanticScore not set, structural score used

def test_falls_back_on_malformed_json():
    # Mock LLM returns "not json"
    # Assert: SemanticScore not set, structural score used, warning logged

def test_combined_score_weighted_correctly():
    # struct=8, semantic=4 → combined = round(8*0.6 + 4*0.4) = round(6.4) = 6
    # Assert: is_promotable = False (combined < 7)

def test_semantic_skipped_below_struct_threshold():
    # struct_score = 5 (< 6)
    # Assert: judge.judge() never called

def test_disabled_by_default():
    # enable_semantic_scoring = False (default)
    # Assert: judge.judge() never called regardless of struct score
```

---

## Success Criteria

- Semantic judge never runs unless `enable_semantic_scoring: true` AND `max_tokens_per_run` is set.
- Structural QualityGate always runs first (fast, free).
- LLM offline or bad response degrades gracefully to structural-only — no blocked promotions.
- Combined score uses 60/40 weighted average.
- Curator notes include semantic critique when judge runs.
- Cost per entity tracked in cost log alongside structural curator work.
