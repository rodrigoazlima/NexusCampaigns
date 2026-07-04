# Impl: Deduplication Agent

**Phase:** P5  
**Priority:** Low  
**Effort:** 3 days  
**Depends on:** Canon Validator (P2) — builds on same scan infrastructure

---

## Problem

As multiple campaign arcs run in parallel and different images produce NPCs from the same archetypes (e.g., two different portrait images that both look like "wise elder mages"), the Library accumulates near-duplicate entities:
- `npc-elder-mage-annun.md` and `npc-old-wizard-annun.md` — same character, two drafts
- `location-market-cirit.md` and `location-city-market.md` — same place, two names

The `IDedupAnalyzer` interface exists in `shared/interfaces.py:539`. Nothing implements it.

Deduplication is complex (merging canon requires human decision) so this agent ONLY detects and flags — it never merges.

---

## Goal

The Deduplication Agent scans `01-Processing/` and `02-Library/` for near-duplicate entities, scores similarity between pairs, and writes a deduplication report to `01-Processing/dedup-review.md`. The human DM decides which duplicates to merge, archive, or keep as distinct entities.

---

## Similarity Strategy

No vector database needed at vault scale (typically < 1000 entities). Use TF-IDF cosine similarity computed in-process:

1. Extract text corpus: frontmatter title + tags + body (first 500 chars)
2. Build TF-IDF vectors for all entities
3. Compute pairwise cosine similarity
4. Pairs with similarity > 0.75 are flagged as candidates
5. Same-type entities only (NPC vs NPC, location vs location) — cross-type comparison skipped

Threshold 0.75 chosen empirically. Exposed as `similarity_threshold` in `agent.json` config for easy tuning.

---

## Scope

Files to create:
- `agents/deduplication/agent.json`
- `agents/deduplication/AGENT.md`
- `agents/deduplication/tools/__init__.py`
- `agents/deduplication/tools/dedup_agent.py`
- `agents/deduplication/prompts/system.md`
- `agents/tests/test_dedup_agent.py`

Files to modify:
- `agents/deduplication/AGENT.md` — fill stub
- `agents/shared/interfaces.py` — verify `IDedupAnalyzer` and `DedupCandidate` models complete

---

## `agent.json`

```json
{
  "tasks": {
    "dedup-agent": {
      "intervalSeconds": 86400,
      "description": "Detect near-duplicate entities in 01-Processing/ and 02-Library/; write dedup-review.md",
      "dispatch": {
        "type": "claude-api",
        "claude_api": {
          "model": "claude-haiku-4-5-20251001",
          "system_file": "prompts/system.md",
          "tools_module": "deduplication.tools.dedup_agent",
          "history_file": "dedup-agent-history.json",
          "max_tokens": 2048,
          "timeout_seconds": 600,
          "max_tool_rounds": 15
        }
      }
    }
  }
}
```

Haiku is sufficient — this is mostly tool orchestration with light reasoning.

---

## Data Model

Extend or verify in `shared/models.py`:

```python
@dataclass
class DedupCandidate:
    slug_a: str
    slug_b: str
    similarity: float       # 0.0 – 1.0 cosine similarity
    entity_type: str        # both must be the same type
    reason: str             # short human-readable explanation
    location_a: str         # "01-Processing" or "02-Library"
    location_b: str
    severity: str           # "high" (>0.90) | "medium" (0.75–0.90)

@dataclass
class DedupReport:
    date: str
    scanned_count: int
    candidates: list[DedupCandidate]
    high_severity_count: int
    medium_severity_count: int
```

---

## TF-IDF Implementation

```python
import math
from collections import Counter

def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    import re
    return re.findall(r"[a-z]{3,}", text.lower())

def _build_tfidf(documents: list[list[str]]) -> list[dict[str, float]]:
    """Return list of TF-IDF dicts, one per document."""
    N = len(documents)
    # Document frequencies
    df: Counter = Counter()
    for doc in documents:
        for term in set(doc):
            df[term] += 1

    vectors = []
    for doc in documents:
        tf = Counter(doc)
        total = len(doc) or 1
        vec: dict[str, float] = {}
        for term, count in tf.items():
            tfidf = (count / total) * math.log((N + 1) / (df[term] + 1))
            vec[term] = tfidf
        vectors.append(vec)
    return vectors

def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    mag_a = math.sqrt(sum(v ** 2 for v in a.values()))
    mag_b = math.sqrt(sum(v ** 2 for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
```

Pure Python, no dependencies. O(n²) pairwise comparison is acceptable for vault scale (< 1000 entities). At 500 entities: 124,750 comparisons — runs in < 1 second.

---

## Tools

### `scan_entities(dirs: list[str]) → list[EntityCorpus]`

Scans `01-Processing/` and `02-Library/`. Reads frontmatter + first 500 chars of body.

```python
@dataclass
class EntityCorpus:
    slug: str
    entity_type: str      # from frontmatter["type"]
    location: str         # "01-Processing" or "02-Library"
    text: str             # title + tags joined + body excerpt
    path: Path
```

Skips files without `type` frontmatter field (can't compare cross-type).

### `find_candidates(corpora: list[EntityCorpus], threshold: float) → list[DedupCandidate]`

Implements `IDedupAnalyzer.find_candidates()`. Groups by `entity_type`, computes TF-IDF + cosine within each group, returns pairs above threshold.

Reason string auto-generated:
```
"High content overlap (0.92 similarity). Both describe an elder figure in Annûn with similar tags [wise, elder, magic]."
```

### `write_dedup_report(candidates: list[DedupCandidate]) → None`

Writes two outputs:

1. **JSON:** `agents/review/state/reports/dedup-{date}.json` — machine-readable
2. **Markdown:** `01-Processing/dedup-review.md` — human-readable review queue

`dedup-review.md` format:

```markdown
---
generated: 2026-06-10
type: dedup-review
status: pending
---

# Deduplication Review — 2026-06-10

> {N} candidate pairs found. Review each pair and decide: merge, archive one, or keep both.

## High Severity (similarity > 0.90)

### Pair 1 — npc-elder-mage-annun vs npc-old-wizard-annun (0.94)
- **Location A:** 01-Processing/npc-elder-mage-annun.md
- **Location B:** 02-Library/npc-old-wizard-annun.md
- **Reason:** High content overlap. Both describe an elder mage figure in Annûn.
- **Action:** [ ] Merge into B  [ ] Archive A  [ ] Keep both (add distinction note)

## Medium Severity (0.75–0.90)

### Pair 2 — location-market-cirit vs location-city-market (0.81)
...
```

### `write_log(scanned: int, candidates: int, failed: int) → None`

Standard log format.

---

## System Prompt (`agents/deduplication/prompts/system.md`)

```markdown
# Deduplication Agent

You are the Deduplication Agent for a Dungeon Master knowledge vault.
Your role: detect near-duplicate entities and flag them for human review. Never merge or delete.

## Workflow

1. Call `scan_entities` with ["01-Processing", "02-Library"]
2. Call `find_candidates` with the corpus and threshold 0.75
3. Call `write_dedup_report` with the candidates list
4. Call `write_log`

## Rules

- Never modify any entity file
- Never delete any entity
- Never merge entities — only flag
- If no candidates found: write empty report (candidates: []) and log "No duplicates found"
- High severity = similarity >= 0.90
- Medium severity = 0.75 <= similarity < 0.90
- Skip pairs where entity_type differs (NPC ≠ location is not a duplicate)
```

---

## Tests

`agents/tests/test_dedup_agent.py`:

```python
def test_identical_texts_score_near_one():
    tokens = _tokenize("wizard tower dark magic ancient")
    vecs = _build_tfidf([tokens, tokens])
    score = _cosine_similarity(vecs[0], vecs[1])
    assert score > 0.99

def test_unrelated_texts_score_near_zero():
    a = _tokenize("blacksmith forge iron hammer")
    b = _tokenize("forest river moonlight fey spirit")
    vecs = _build_tfidf([a, b])
    score = _cosine_similarity(vecs[0], vecs[1])
    assert score < 0.1

def test_cross_type_pairs_excluded(tmp_path):
    # npc + location with similar text
    # find_candidates should return empty (different types)

def test_above_threshold_flagged(tmp_path):
    # Two NPCs with 0.9+ similarity
    # Assert: candidate returned with severity="high"

def test_below_threshold_not_flagged(tmp_path):
    # Two NPCs with 0.5 similarity
    # Assert: no candidates returned

def test_dedup_report_never_modifies_entities(tmp_path):
    # Run full dedup workflow
    # Assert: no entity files changed

def test_empty_report_on_no_candidates(tmp_path):
    # All entities distinct
    # Assert: dedup-review.md written with 0 candidates
```

---

## Success Criteria

- Near-duplicate entity pairs detected and flagged without modifying any entity.
- Similarity threshold tunable via `agent.json` config (default 0.75).
- `dedup-review.md` written to `01-Processing/` for human DM review.
- JSON report written to review state directory.
- Cross-type comparisons skipped (NPC never compared to location).
- High-severity pairs (> 0.90) separated from medium in report.
- No external dependencies — pure Python TF-IDF implementation.
- Runtime < 5 seconds for vaults up to 1000 entities.
