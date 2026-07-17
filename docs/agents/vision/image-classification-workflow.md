# Vision Agent - Image Classification Workflow

How `classify_image_full()` (`agents/vision/tools/classify_images.py`) turns one
inbox image into a `VisionClassification`. This is the narrative walkthrough;
`docs/specs/agents/agent-vision.spec.md` is the normative contract and wins on
any conflict.

## Why steps are split

The original implementation sent one giant prompt (`classify-image.txt`) asking
the vision LLM to determine image type, run a full visual analysis, classify
PF2e ancestry/class/environment/element, write an AI-recreation prompt, and
write a flavor description, all in a single JSON response. Two problems fell
out of that:

- **Battlemap under-detection.** A gridless top-down city map (a real
  `DarkestMaps`-style VTT asset, straight-down camera, no grid lines) was
  classified as `scene` instead of `battlemap`, because "top-down tactical
  map" was buried as one bullet among many and easy for the model to
  under-weight against everything else it was juggling in the same turn.
- **LLM-driven branching.** The prompt asked the model to self-select which
  PF2e fields applied ("if type == portrait or body ... if type == battlemap
  or scene ...") even though the branch is fully determined by information
  the pipeline *already has* once the type is known - asking the LLM to
  re-decide it wastes a judgment call on something that isn't actually
  ambiguous once the type is set, and leaves it to interpret conditional
  prose correctly.

The fix: one focused LLM turn per step, an explicit completion contract per
step, and the type-based branch chosen in Python instead of prompt text.

## The conversation

One `LLMClient` conversation carries the image (`_image_content_block`,
attached once on the first turn) through up to `max_conversation_messages`
turns (default 20). It is composed of two phases:

```
system prompt
├─ STEP 1: type                      ─┐
├─ STEP 2: visual analysis            │  4 required steps
├─ STEP 3: pf2e (character|environment)│  (_run_required_step,
├─ STEP 4: flavor description         ┘   retries + abort)
├─ cycle: confirm type + tags          ─┐
├─ cycle: entity type + tags            │  3 optional cycles
└─ cycle: tag-library refinement       ─┘  (degrade gracefully)
```

### Required steps (1-4)

Each step is one user turn + one assistant reply, sent by `_run_required_step`:

| # | File | Asks for | Validates |
|---|---|---|---|
| 1 | `prompts/classify-step1-type.txt` | `{"type": "..."}` | one of portrait/body/battlemap/scene |
| 2 | `prompts/classify-step2-visual.txt` | `{"visual_analysis": {...}}` | `visual_analysis` is present and is an object |
| 3 | `prompts/classify-step3-pf2e-character.txt` **or** `-environment.txt` | ancestry/class/creature_type **or** environment/element | (shape only - PF2e vocab is open-ended, see `agent-vision.spec.md`) |
| 4 | `prompts/classify-step4-description.txt` | `{"description": "..."}` | non-empty string |

STEP 3's file choice is the key design point: `classify_image_full` reads
STEP 1's already-parsed `type` and picks `pf2e_character` for portrait/body or
`pf2e_environment` for battlemap/scene *before* building the turn. The model
is never shown both variants and never asked to decide which applies - by the
time STEP 3 runs, that decision has already been made in code.

If a required step's response fails to parse as JSON, isn't a JSON object, or
fails its validator, `_run_required_step` appends a short corrective nudge
("That was not valid JSON... return ONLY valid JSON matching the requested
schema") and retries, up to `step_max_retries` times (default 2, so 3 attempts
total), sleeping `step_retry_backoff_seconds` (default 3s) between attempts.
Exhausting retries raises `LLMResponseError`, which aborts *only that image* -
`main()`'s per-image loop catches it, records `status: failed` in
`processed-images.json`, and continues the batch. An `LLMOfflineError` from
the LLM client is never retried at the step level; it propagates immediately
so `main()`'s own one-time "LM Studio evicted this model, wait and retry"
handling applies instead of the step swallowing it.

Once all 4 required steps succeed, their answers are merged into one dict
matching the original combined JSON shape (`type`, `ancestry`, `class`,
`creature_type`, `element`, `environment`, `description`, `visual_analysis`) and
validated via `VisionClassification.model_validate()` - downstream code
(`_write_draft`, slug builders, `_is_object_in_scene_bucket`, etc.) is
unaffected by the step split; it never sees anything but the same
`VisionClassification` it always did.

### Optional cycles (5-7)

These reuse the pre-split behavior unchanged: each is a best-effort follow-up
turn that improves the result (a second opinion on `type`, an `entity_type`
guess, and alignment against the classification agent's shared tag library),
but a parse failure or LLM error here just keeps whatever was already
collected - no retry, no abort. Only the 4 required steps can fail an image.

## Battlemap detection fix

`classify-step1-type.txt` now defines the type criterion by **camera angle**
rather than by the presence of tactical-map furniture (grid lines, a scale
ruler, VTT branding):

> `battlemap` → camera looks straight down (bird's-eye/orthographic top-down
> view), regardless of whether grid lines, a scale ruler, or VTT/publisher
> branding are visible - streets, rooftops, and floor plans seen from
> directly above are battlemap even with no grid drawn
>
> `scene` → ... viewed at eye level or an angled/perspective camera (not
> straight down)

This is also now its own isolated LLM turn (previously one bullet inside a
five-step combined prompt), so the model's entire attention for that turn is
the type question alone.

## Configuration

All numeric tunables (batch size, retry counts, message cap, token budgets,
tag-count goal, face-match threshold) are external, not hardcoded:

- **Default**: `agents/registry.yaml` → `agents.vision.options`
- **Per-machine override**: `agents/vision/agent.json` → `tasks.vision-agent.pipeline`
  (same file, same precedence pattern already used for `llm.timeout_seconds`/
  `llm.model_key` overrides)
- **Hardcoded fallback**: `classify_images.py`'s `_PIPELINE_DEFAULTS`, used only
  if `registry.yaml` is missing/malformed

See `agents/vision/AGENT.md`'s "Pipeline Configuration" table for the full key
list and current defaults. `agent.json` is gitignored (machine-local); a fresh
clone gets one scaffolded by the maintenance worker from
`nexus.workers.maintenance._AGENT_JSON_SPECS["vision"]`, which carries the
same defaults.

## What changed vs. the old single-prompt design

| | Before | After |
|---|---|---|
| Prompt file(s) | 1 (`classify-image.txt`, 5 STEP sections in one turn) | 5 (`classify-step1..4-*.txt`, one turn each) |
| Type→PF2e branch | LLM if/else inside the prompt text | Python branch on STEP 1's parsed result |
| Message cap | 10 | 20 (`max_conversation_messages`, configurable) |
| Failure handling (steps 1-4) | Cycle 1 failed the whole image immediately, no retry | Retries up to `step_max_retries` times, then aborts the image |
| Failure handling (cycles 5-7) | Degrades gracefully (unchanged) | Degrades gracefully (unchanged) |
| `ai_prompt` (image-generation recreation prompt) | Generated every run, never consumed anywhere in the codebase | Dropped - dead output, nothing read it |
| Config source | Hardcoded module constants | `registry.yaml` default + `agent.json` override |
