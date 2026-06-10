---
name: vision
purpose: >
  Classifies RPG images in 00-Inbox/images/ using Qwen3-VL vision model via LM Studio.
  Detects image type (portrait/body/battlemap/scene/token), renames files to canonical
  slug format, writes AGENTS.md-compliant draft entities to 01-Processing/, runs
  face-match to link tokens to their source portraits, maintains processed-images.json.
inputs:
  - vault://00-Inbox/images/**/*.{png,jpg,jpeg,webp}
  - state/processed-images.json
  - state/token-links.json
  - .shared/state/inbox-queue.json
  - LLM: http://localhost:1234/v1/chat/completions (Qwen3-VL)
outputs:
  - vault://01-Processing/{slug}.md (draft entity per image)
  - vault://01-Processing/Images Index.md (appended row)
  - vault://00-Inbox/images/{folder}/{slug}.{ext} (renamed image)
  - state/processed-images.json (updated index)
  - state/token-links.json (face match links)
  - .shared/state/inbox-queue.json (agents.vision = done)
  - state/logs/06-classify-images_YYYY-MM-DD.log
dependencies:
  - ingestion
dispatch_config: agent.json
owned_tools:
  - tools/06-classify-images.ps1
  - tools/06-match-token.py
responsibilities:
  - Pre-flight check LM Studio at localhost:1234 before processing batch
  - Detect transparent-corner PNGs as tokens (alpha sample 8 edge points)
  - For tokens: run face-match via 06-match-token.py against non-token images in same folder
  - Inherit classification metadata from matched source portrait if face-match succeeds
  - Call Qwen3-VL with base64-encoded image (resize to max 1024px on longest side, JPEG 85%)
  - Validate LLM JSON response against allowed race/class/element/environment enums
  - Build target filename slug; bump existing same-named file to counter suffix
  - Write AGENTS.md-compliant draft to 01-Processing/ (status: draft, quality: 0, reviewed: false)
  - Append row to Images Index.md
  - Save result to processed-images.json after each classified image (not at batch end)
  - Update inbox-queue.json agents.vision = done for each processed file
  - Abort batch silently on connection-error (do not mark image as failed)
  - Batch: 10 images per run; process non-PNG before PNG (tokens last)
restrictions:
  - Must not approve content
  - Must not modify 02-Library/
  - Must not mark images as failed on connection-error (only on repeated API errors)
  - Max 3 LLM retries per image with 3s backoff
state_files:
  - state/processed-images.json
  - state/processed-images.txt (legacy migration source)
  - state/token-links.json
commit_scope:
  - knowledge-base/00-Inbox/images
  - knowledge-base/01-Processing
  - .agents/vision/state
  - .shared/state
---

## Valid Classification Values

### Image Types
portrait · body · battlemap · scene · token

### Races
human · elf · dark-elf · dwarf · orc · goblin · troll · ogre · dragon · angel · devil · demon · undead · skeleton · zombie · vampire · werewolf · spirit

### Classes
warrior · mage · archer · cleric · paladin · necromancer · assassin · monster · none

### Elements
fire · water · earth · air · nature · dark · light · none

### Environments (battlemap/scene)
dungeon · cave · forest · city · tavern · desert · snow · sea · swamp · ruins · temple · castle · plains · mountain · interior · exterior · none
