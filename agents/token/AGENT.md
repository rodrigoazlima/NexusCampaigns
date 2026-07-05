---
name: token
purpose: >
  Generates circular 512×512 portrait tokens from classified character images. Uses
  MediaPipe face detection (falling back to OpenCV Haar, then upper-center crop) to
  crop and center the face, then composites the result into a moldura ring frame.
  No LLM. Pure computer vision pipeline.
inputs:
  - agents/vision/state/processed-images.json (read-only)
  - state/10-generate-tokens.json (config)
  - vault://05-Assets/tokens/frames/frame.png (frame asset)
  - vault://00-Inbox/images/**/*.{png,jpg,jpeg,webp}
outputs:
  - vault://00-Inbox/images/**/{stem}-token.png (circular token)
  - state/generated-tokens.json (updated index)
  - state/logs/10-generate-tokens_YYYY-MM-DD.log
dependencies:
  - vision
dispatch_config: agent.json
owned_tools:
  - tools/generate_tokens.py
responsibilities:
  - Load config from state/10-generate-tokens.json (size, padding, ratios, moldura path)
  - Filter processed-images.json to status=ok, isToken=false, type not in battlemap/scene
  - Skip images already in generated-tokens.json unless --force
  - Detect face via MediaPipe → OpenCV Haar → upper-center fallback
  - Apply forehead_ratio and body_ratio to extend crop to full head+chest
  - Apply focus_head CSS-like offset (top/right/bottom/left in % of crop size)
  - Apply anti-aliased circle mask via 4× supersampled ellipse
  - Composite character circle under moldura ring frame
  - Save as 512×512 transparent PNG alongside source image
  - Record in generated-tokens.json per source image key
  - Batch: 10 per run; support --source single-image mode
restrictions:
  - Must not call any LLM
  - Must not modify 02-Library/
  - Must not overwrite existing tokens unless --force is passed
  - Token output stays in 00-Inbox/images/ (promotion to 05-Assets/ is a human curation step)
state_files:
  - state/generated-tokens.json
  - state/10-generate-tokens.json
commit_scope:
  - .knowledge-base/00-Inbox/images
---
