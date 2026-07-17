# Investigation + plan: vision agent classification unreliability

**Date**: 2026-07-17
**Trigger**: dashboard Vision Agent panel showing 15 runs / 1 processed / 125 failed.
**Status**: root cause #1 fixed and verified live. #2-#4 are plan only, not yet implemented.

## Symptom

Every classification attempt since commit `5b38554` (`refactor(vision-agent): replace
single-step image classification with multi-step pipeline`) failed with the identical
error, regardless of image:

```
Classification failed for <file>: required step never returned valid JSON after 3
attempt(s): step 4: missing/empty description [hash=... uuid=... path=...]
```

125/126 processed-image entries in `agents/vision/state/processed-images.json` are
`status: failed`. 28 more images sit `Skip`/`Pending` in the dashboard queue, never
reached.

## Investigation methodology

Log-reading alone only gets you to "step 4 always fails" - it doesn't tell you *why*,
because `_run_required_step`'s error message (`classify_images.py:1192-1194`) reports
`last_err` from `_validate_step4`, not the raw model output that caused it. Finding the
actual shape of the bad response required calling the real pipeline against the real
LM Studio endpoint directly (no mocking - this repo's tests never mock the daemon/LLM
either, same principle applies to ad-hoc debugging) and printing the raw pre-validation
text. Reusable harness (run from `.testing/nexus/`, LM Studio must be up at
`localhost:1234` with `qwen3-vl-4b-instruct` loaded - check via `curl -s
http://localhost:1234/v1/models`):

```python
import sys
sys.path.insert(0, 'system/src')
sys.path.insert(0, 'agents/vision/tools')
import classify_images as ci
from pathlib import Path

client = ci.LLMClient(ci._LLM_CFG)
img = Path('.knowledge-base/00-Inbox/images/unknown.portrait.jpg')  # any real inbox image
b64_block = ci._image_content_block(img)
step_prompts = ci._load_step_prompts()
messages = [{'role': 'system', 'content': ci._VISION_SYSTEM_PROMPT}]

step1 = ci._run_required_step(messages, client, [b64_block, {'type': 'text', 'text': step_prompts.get('type', '')}], ci._STEP_MAX_TOKENS['type'], validate=ci._validate_step1)
step2 = ci._run_required_step(messages, client, step_prompts.get('visual', ''), ci._STEP_MAX_TOKENS['visual'], validate=ci._validate_step2)
is_character = step1['type'] in ('portrait', 'body')
step3 = ci._run_required_step(messages, client, step_prompts.get('pf2e_character' if is_character else 'pf2e_environment', ''), ci._STEP_MAX_TOKENS['pf2e'])

# To inspect a step BEFORE its validator runs (i.e. to see the raw shape that fails
# validation), call client.chat(...) directly instead of _run_required_step and print
# repr(raw_text) - that's how root cause #1's nested-object shape was found.
raw4 = client.chat(messages + [{'role': 'user', 'content': step_prompts.get('description', '')}], max_tokens=ci._STEP_MAX_TOKENS['description'])
print('STEP4 RAW REPR:', repr(raw4))
```

This is how each root cause below was confirmed - not inferred from reading the prompt
text, but by actually running it against the live model and inspecting the exact JSON
returned. **Gotcha for whoever continues this**: `unknown.portrait.jpg` (the test image
used throughout) is misleadingly named - it is actually a photo of a sword on a plain
background, not a person. That's *why* root cause #2's `subject.*` fields were correctly
empty (no person in frame) but is unrelated to why `equipment.weapons` was wrong (that's
a genuine bug, not an artifact of the test image - the sword is clearly visible and
should have produced a plain-string tag).

Also confirmed live and **not** touched: step1 (`classify-step1-type.txt`) and step3
(`classify-step3-pf2e-character.txt` / `-environment.txt`) both work correctly as-is -
they use closed pipe-delimited enums (`"portrait|body|battlemap|scene"`) or short
enumerated vocab lists rather than blank JSON templates, so the model has no room to
invent structure. Confirmed via the same harness (`STEP1 OK`, `STEP3 OK` in the raw
session output). Don't spend time re-auditing those two - the defect pattern is specific
to templates with **no filled example value**, and only step2 and (pre-fix) step4 had it.

## Rationale for the fix ordering above

- **Prompt fix over defensive code, as the primary fix (root causes #1, #2)**: both bugs
  stem from the same root - a JSON schema shown to the model as an all-blank template,
  with no example of what a *filled* value looks like. A small (4B) instruct model at
  temperature 0 has nothing to anchor its output shape to and pattern-matches structure
  from whatever surrounding text looks most schema-like (numbered sentence labels →
  nested keys; unlabeled empty arrays → objects with plausible sub-keys). Fixing the
  prompt addresses the actual cause once; patching `_extract_candidate_tags` or
  `_validate_step2` alone would leave the model free to invent yet another wrong shape
  next time the image content or model version shifts, and would still discard
  `visual_analysis` content that never makes it into `candidate_tags` at all (e.g. if a
  future field also gets nested, some other downstream reader silently loses it too).
- **Defensive `_extract_candidate_tags` hardening (item 2) is still worth doing anyway**,
  in addition to the prompt fix, not instead of it - small local models are inherently
  unreliable even with a good prompt, and this one function is the single choke point
  all candidate tags pass through, so hardening it once covers every future prompt
  regression at near-zero cost. This is a "belt and suspenders," not a substitute for
  fixing the prompt.
- **Retry mechanism (item 3) is independent of the prompt fixes** and must happen anyway:
  even a perfect prompt fix does not retroactively un-fail the 125 already-failed images,
  because `_candidate_images` permanently excludes anything already in `pathIndex`
  regardless of *why* it's there. Skipping this step means the fix would only be visible
  on the *next* fresh batch of uploads, not on the backlog that prompted this
  investigation - easy to mistake for "fix didn't work" if skipped.
- **Cycles 2-4 exception handling (item 4) is lowest urgency** of the four real bugs
  because it's a narrower failure window (only triggers during an LM Studio model swap
  mid-classification, not on every run like #1/#2) and its blast radius is smaller
  (sparse tags on one image, not a hard failure or vault-wide tag loss). Still worth
  fixing since it's currently silent and unmeasurable - nothing today would tell you it
  happened without diffing tag counts against expectation by hand.

## Root cause #1 (FIXED): step4 prompt shape mismatch

`agents/vision/prompts/classify-step4-description.txt` asked for the description as a
numbered list:

```
Sentence 1: Describe the visible subject and setting.
Sentence 2: Describe the atmosphere, lighting, and visual highlights.
Sentence 3: Suggest a possible encounter, NPC role, or scene usage...
```

...then showed `{"description": "..."}` as the only JSON example. The vision model
(`qwen3-vl-4b-instruct` via LM Studio, temperature 0 - deterministic) pattern-matched
the numbered list into a JSON object with one key per sentence instead of one string,
reproduced live before the fix:

```
STEP4 RAW REPR: '{\n  "description": {\n    "sentence1": "",\n    "sentence2": "",\n    "sentence3": ""\n  }\n}'
```

`_validate_step4` (`classify_images.py:1143-1145`) requires `isinstance(d["description"], str)`
- a dict fails validation every time, deterministically, for every image. `_run_required_step`
retries 3x with the same prompt (temp 0 → identical output each retry), then raises.

**Fix applied**: rewrote the prompt as one flowing single-string instruction with a
concrete filled example (real prose) instead of the `"..."` placeholder. Verified live
against LM Studio, same image, full step1-4 pipeline:

```
STEP4 VALIDATED OK: {'description': 'A single sword stands upright against a plain
gray backdrop. Its blade gleams with sharp edges and a subtle etching near the hilt;
the grip is wrapped in dark, textured material topped by a golden pommel. A noble
warrior's weapon, perhaps displayed for sale or inspection at a market stall.'}
```

File changed: `agents/vision/prompts/classify-step4-description.txt`.

## Root cause #2 (PLAN ONLY): step2 prompt causes silent tag data loss

`agents/vision/prompts/classify-step2-visual.txt` is a ~60-field nested JSON template
with every value left as an empty string/array placeholder - no filled example anywhere.
Live-tested against a plain sword photo (same test image as above):

```json
"equipment": {
  "weapons": [
    {"type": "sword", "description": ""}
  ],
  ...
}
```

The model nests each equipment/clothing/feature item as an object (`{type, description}`)
instead of a plain string, since nothing in the prompt shows what a *filled* array entry
should look like. `_extract_candidate_tags` (`classify_images.py:957-975`):

```python
for item in (analysis.get(section) or {}).get(key) or []:
    if not isinstance(item, str):
        continue          # <-- silently drops the dict-shaped "sword" entry
```

`_validate_step2` (`classify_images.py:1138-1140`) only checks `isinstance(dict)` -
never inspects content - so this never raises or logs. The image is marked `status: ok`
with a real, visible weapon silently missing from `candidate_tags`. No error, no warning,
nothing to grep for. This is the same "blank template, no example" prompt defect that
caused root cause #1, but here it degrades output quality instead of hard-failing, so it
was invisible in the dashboard's failed-count.

**Not yet fixed.**

## Root cause #3 (PLAN ONLY): no retry path for failed images

`_candidate_images` (`classify_images.py:299-316`) skips any path already present in
`state["pathIndex"]`. Failed images are recorded there under key `path:{rel}`
(`classify_images.py:1391-1408`) alongside successful ones (keyed by sha256) - both are
permanently excluded from future batches. Unlike the worker contract's queue workers
(`reruns >= 3` poison-pill, surfaced by the maintenance worker), the vision agent has
**zero** automatic retry mechanism. An image that fails once is dead forever unless
something manually edits `processed-images.json`.

Concretely: the 125 images already marked failed by root cause #1 will **stay failed**
even now that the step4 prompt is fixed, unless their `path:{rel}` entries are cleared.

**Not yet fixed.**

## Root cause #4 (PLAN ONLY): LLMOfflineError swallowed inside cycles 2-4

Cycles 2-4 (`classify_images.py:1267-1304` - type-confirm, entity-type, tag-library
refinement) each wrap their LLM call in:

```python
except (LLMOfflineError, LLMResponseError, Exception):
    pass  # keep the required steps' type/tags - never fail the image over this
```

The tuple is redundant (`Exception` already covers the other two) and, more importantly,
swallows `LLMOfflineError` too. LM Studio can only hold one model loaded at a time; a
concurrent request for another model briefly evicts this one (comment at
`classify_images.py:1376-1379` acknowledges this exact scenario for the *required* steps
and retries once). But if that eviction happens during cycles 2-4 instead, nothing
propagates - `main()`'s offline-retry wrapper (lines 1372-1386) only wraps the call to
`classify_image_full`, and since cycles 2-4 never re-raise, the image is written with
`status: ok` but sparse/no tags and `entity_type: none`, permanently, with no signal
anything degraded.

**Not yet fixed.**

## Fix plan (priority order, not yet applied)

1. **Rewrite `classify-step2-visual.txt`** the same way as step4: one concrete filled
   example instead of an all-blank template, explicit instruction that array items are
   short plain strings (e.g. `"weapons": ["longsword"]`), not objects.
2. **Harden `_extract_candidate_tags`** defensively: if an array item is a dict, try
   `item.get("type") or item.get("name")` before discarding, so a still-imperfect model
   response doesn't silently lose data even if the prompt fix isn't 100% effective.
3. **Add a retry/reclassify path**: strip `path:{rel}` entries from `pathIndex`/`images`
   (script or maintenance-worker hook) so `_candidate_images` picks failed images back up.
   One-time follow-up: clear the 125 existing failures so they reprocess under the fixed
   prompt.
4. **Fix cycles 2-4 exception handling**: catch `LLMOfflineError` specifically and
   re-raise so it reaches `main()`'s existing retry-once/abort-batch logic; keep the
   broad catch only for parse/format errors. Drops the redundant exception tuple as a
   side effect.
5. *(optional / lower priority)* Log a warning when a classification "succeeds" but
   `visual_analysis` content is suspiciously sparse relative to what the image plausibly
   contains - there is currently zero observability into silent quality loss like #2.

## Verification plan once implemented

- Re-run the same live step1-4 harness used above (`agents/vision/tools/classify_images.py`
  imported directly, `classify_image_full` called against a known test image) and confirm
  `visual_analysis.equipment.weapons` contains plain strings, `candidate_tags` includes
  the weapon.
- Clear a handful of `path:` failure entries, re-run `python -m nexus.runner --task
  vision-agent --force`, confirm they move to `status: ok` with non-trivial tag counts.
- `pytest agents/tests -k vision` (existing suite) must still pass.

## Notes for the next agent picking this up

- **Nothing here has been implemented except root cause #1.** `classify-step4-description.txt`
  is the only file changed so far. Items 1-5 under "Fix plan" are still todo, in that order.
- **State file schema, so you don't have to re-derive it**: `agents/vision/state/processed-images.json`
  is `{version, images: {sha256: entry}, pathIndex: {relpath: sha256_or_"path:"+relpath}}`.
  A failed entry has no real sha256 key in `images` - it's stored under the literal string
  key `f"path:{relpath}"` in both `images` and `pathIndex` (`classify_images.py:1391-1408`).
  To clear a failed entry for retry (item 3), delete both the `images["path:...']` entry
  and the matching `pathIndex["..."]` entry, then `_save_state()` (atomic tmp-rename write,
  already handles this correctly - don't hand-edit the JSON file while the runner might be
  mid-cycle, use the lock/save helpers already in the module).
- **`_get_folder_candidates` (`classify_images.py:323-351`) already filters `path:` keys out**
  via `sha_or_key.startswith("path:")` - this is the existing precedent for how the codebase
  distinguishes failed from successful entries; item 3's retry script should follow the same
  convention rather than inventing a new one.
- **Don't touch `classify-step1-type.txt` or `classify-step3-pf2e-*.txt`** - confirmed
  working correctly live (see Investigation methodology above). The defect is specific to
  step2 and was specific to step4 before the fix.
- **To verify item 1 (step2 prompt rewrite)**: rerun the harness script above through step2
  only, check `visual_analysis.equipment.weapons` (and the other `_CANDIDATE_TAG_PATHS`
  entries at `classify_images.py:937-954`) come back as arrays of plain strings, not
  objects, for an image with visible equipment.
- **`agents/vision/CLAUDE.md` and root `CLAUDE.md`** (this project's own docs) describe the
  intended 4-required-steps + 3-optional-cycles architecture in more detail than this doc -
  read those first if the flow itself (not just these 4 bugs) needs to change.
- Temperature is pinned to 0 for this LLM client (`llm_client.py:85`, per
  `llm-integration.spec.md`) - every finding above was reproduced deterministically
  (same input → same broken output every time), so verification after a fix is a single
  run, not a statistical sample. If a fix appears to "sometimes" work and "sometimes"
  not against the same image, something else is wrong (e.g. LM Studio swapped models
  mid-session) - it is not expected model variance.
