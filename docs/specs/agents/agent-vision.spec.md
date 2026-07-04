# Agent Spec — Vision

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
     Invoke-VisionLLM → classify via Qwen3-VL
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

---

## Image Filename Slug Format

| Type | Format |
|------|--------|
| battlemap / scene | `{type}-{environment}.ext` |
| portrait | `{race}-{class}-{element}.portrait.ext` |
| body | `{race}-{class}-{element}.body.ext` |
| token (PNG with alpha) | `{race}-{class}-{element}.token.ext` |

Collision resolution: bump existing file to `{base}-N.{suffix}.ext`.

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
Connection-error images NOT stored — retried next run.

---

## Constraints

- Cannot approve content
- Cannot modify `02-Library/`
