# Agent Spec — Vision (`06-classify-images.ps1`)

**Trigger:** hourly  
**Input:** `00-Inbox/images/**/*.{png,jpg,jpeg,webp}` not yet in `processed-images.json` (path index)  
**Output:** renamed image files, `01-Processing/*.md` drafts, `01-Processing/Images Index.md`, `processed-images.json`  
**Dependency:** LM Studio at `http://localhost:1234` with model `qwen3-vl-4b-instruct`

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
8. Append-WikiRow → Images Index.md
9. Update processed-images.json (v2 schema)
10. Update inbox-queue.json agents.vision = done
```

**Batch size:** 10 images per run. Non-PNG images processed first (tokens are PNG).  
**Pre-flight:** if LM Studio offline → exit 0 (no images marked failed, retry next run).

---

## LLM Prompt Contract

Returns JSON only:

```json
{
  "type": "portrait | body | battlemap | scene",
  "race": "human | elf | dark-elf | dwarf | orc | goblin | troll | ogre | dragon | angel | devil | demon | undead | skeleton | zombie | vampire | werewolf | spirit",
  "class": "warrior | mage | archer | cleric | paladin | necromancer | assassin | monster | none",
  "element": "fire | water | earth | air | nature | dark | light | none",
  "environment": "dungeon | cave | forest | city | tavern | desert | snow | sea | swamp | ruins | temple | castle | plains | mountain | interior | exterior | none",
  "description": "1-2 sentence string"
}
```

- `battlemap` / `scene`: race/class/element set to `none`
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
      "race": "string",
      "class": "string",
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
