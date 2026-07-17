# Agent Spec - Vision

**Trigger:** hourly  
**Input:** `00-Inbox/images/**/*.{png,jpg,jpeg,webp}` not yet in `agents/vision/state/processed-images.json`  
**Output:** renamed image files, `01-Processing/*.md` drafts, `agents/vision/state/processed-images.json`  
**Dependency:** LM Studio at `http://localhost:1234` with model `qwen3-vl-4b-instruct`  
**Dispatch:** `claude-api` · `claude-sonnet-4-6` · `tools_module: vision.tools.classify_images`

---

## Processing Flow (per image)

```
1. SHA256 hash → check processed-images.json pathIndex
2. Test-IsToken: PNG with ≥2 transparent corner/edge pixels → isToken=true
3. if isToken:
     GetFolderCandidates → non-token, non-battlemap images in same folder
     Invoke-TokenFaceMatch (Python face distance) → inherit meta from matched image
   else:
     classify_image_full() → bounded multi-cycle conversation via Qwen3-VL (see below)
4. Resolve-TargetFilename → slug, bump existing if collision
5. Rename image
6. Compute SHA256 of renamed file
7. Write-ImageMarkdown → 01-Processing/{slug}.md
8. Update processed-images.json (v2 schema)
9. Update inbox-queue.json agents.vision = done
```

**Batch size:** 10 images per run. Non-PNG images processed first (tokens are PNG).  
**Pre-flight:** if LM Studio offline → exit 0 (no images marked failed, retry next run).

---

## LLM Prompt Contract

Returns JSON only:

```json
{
  "type": "portrait | body | battlemap | scene",
  "ancestry": "open PF2e ancestry string (see PF2E_ANCESTRIES in models.py)",
  "class": "open PF2e class string (see PF2E_CLASSES in models.py)",
  "creature_type": "PF2e creature trait | none",
  "element": "fire | water | earth | air | metal | wood | nature | dark | light | void | vitality | none",
  "environment": "dungeon | cave | forest | city | tavern | desert | snow | sea | swamp | ruins | temple | castle | plains | mountain | volcano | underwater | sky | astral | shadow | abyss | interior | exterior | none",
  "description": "1-2 sentence string"
}
```

- `battlemap` / `scene`: ancestry/class/creature_type/element set to `none`
- `portrait` / `body`: environment set to `none`

The same LLM response also includes a `visual_analysis` block (equipment,
clothing, fantasy_features, environment_details, etc. - see
`prompts/classify-image.txt`). `_extract_candidate_tags()` flattens a fixed
allowlist of its array leaves (weapons, tools, materials, creatures, ...) into
a seed tag list - a free-form brainstorm, not validated against any
vocabulary - carried forward into the follow-up cycles below.

---

## Multi-Cycle Conversation (`classify_image_full`)

The prompt above is only cycle 1. `classify_image_full(img_path, client, prompt, is_tk)`
(public - importable by other agents/system code) keeps the same image in
conversation context for up to **10 messages total** (1 system + 4 × user/assistant):

1. **Clean** - the LLM Prompt Contract above, unchanged. Seeds the tag list via `_extract_candidate_tags`.
2. **Image type + tags** - confirms `type` and asks for more concrete tags, told the running count.
3. **Entity type + tags** - infers the note's eventual `EntityType` (npc/location/quest/item/etc., same 18-value taxonomy as `agent-classification.spec.md`), plus more tags.
4. **Tag-library refinement** - `refine_tags_with_library(img_path, client, current_tags, entity_type_hint, library, history=...)` (also public, independently callable with `history=None` for a fresh conversation) sends the top known tags from classification agent's `state/tag-library.json` (read-only here - classification owns writes) and asks the model to align/finalize. The LLM's `final_tags` are **merged** into `current_tags`, never used to replace them wholesale - otherwise a model that rephrases (e.g. "weapon" → "stylized sword") instead of listing both would silently erase a tag an earlier cycle already grounded in the image's own `visual_analysis`.

Every tag appended at any cycle (including the cycle-1 harvest) passes
`_is_concrete_tag()` - 1-6 words - before being kept. Prompts ask for
"short (1-3 word)" tags but nothing previously enforced that, so a full
`visual_analysis` sentence could land in frontmatter `tags:` as if it were
one tag.

**Completion goal:** ≥6 tags and both categories set by the end. No message budget for corrective retries - a cycle whose response fails to parse (or errors: `LLMOfflineError`/`LLMResponseError`/other) keeps the prior cycle's values rather than spending a message on "please retry." Only cycle 1's errors propagate to the caller (same contract the old single-call `_classify_one` had); cycles 2-4 degrade gracefully so a hiccup mid-conversation never fails an otherwise-classifiable image.

The final tag list (`VisionClassification.candidate_tags`) and `entity_type` **are** written to the note's frontmatter by `_write_draft` - no longer state-only, since cycle 4 has already aligned them against the shared tag library.

---

## Image Filename Slug Format

| Type | Format |
|------|--------|
| battlemap / scene | `{type}-{environment}.ext` |
| battlemap / scene, entity_type is an object (see below) | `{entity_type}-{descriptor}.ext` |
| portrait | `{race}-{class}-{element}.portrait.ext` |
| body | `{race}-{class}-{element}.body.ext` |
| token (PNG with alpha) | `{race}-{class}-{element}.token.ext` |

Collision resolution: bump existing file to `{base}-N.{suffix}.ext`.

### Object-in-scene-bucket override

STEP 1 of the classify-image prompt offers only 4 structural types - there is
no "isolated object" option - so a photographed weapon/artifact with little
visible environment gets forced into `scene` (or `battlemap`) by elimination.
Cycle 3's `entity_type` is what actually reveals this: if `type` is
`scene`/`battlemap` and `entity_type` is `item` or `artifact`,
`_is_object_in_scene_bucket()` is true and:

Deliberately narrow - not "any entity_type that isn't place-like". A
scene/battlemap landing on entity_type `creature` or `npc` is left alone: a
monster or character standing in an environment shot is still genuinely a
scene, and forcing it through the object template below would be a
regression, not a fix. Only `item`/`artifact` can never legitimately be the
environment itself.

- the image filename slug and entity slug are built from
  `{entity_type}-{descriptor}` (`build_entity_slug`) instead of
  `{type}-{environment}` - `descriptor` is the first candidate tag that
  survives slugification, falling back to `environment` if none did
- the draft body uses `_item_body()` (Description / Visual Details / DM
  Notes / Details) instead of the scene/battlemap Atmosphere template

Without this override, unrelated object photos with no clear environment
all resolve to the same `scene-interior`/`scene-unknown` bucket and collide
into a meaningless, collision-numbered name family (`scene-interior-01`,
`-02`, `-03`, ...) instead of a name that reflects what the image actually
shows.

---

## processed-images.json v2 Schema

```json
{
  "version": 2,
  "images": {
    "{sha256}": {
      "path": "relative/path/from/vault",
      "processedAt": "ISO-8601",
      "originalName": "string",
      "type": "portrait | body | battlemap | scene",
      "ancestry": "string",
      "class": "string",
      "creature_type": "string",
      "element": "string",
      "environment": "string",
      "description": "string",
      "candidate_tags": ["string"],
      "entity_type": "string",
      "sha256": "string",
      "isToken": true,
      "status": "ok | failed | migrated"
    }
  },
  "pathIndex": {
    "relative/path": "{sha256} | path:{relative/path}"
  }
}
```

Failed images stored with pseudo-key `path:{rel}` and `status: failed`.  
Connection-error images NOT stored - retried next run.

---

## Constraints

- Cannot approve content
- Cannot modify `02-Library/`
