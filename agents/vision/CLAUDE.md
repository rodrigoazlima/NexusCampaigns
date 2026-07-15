# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This is the **vision agent** (`agents/vision/`) inside the Nexus Campaigns monorepo. Full pipeline architecture lives in the root `../../CLAUDE.md` and `../../AGENTS.md` — read those for the multi-agent runner, vault folder rules, and metadata standard. This file covers only what's specific to working inside `agents/vision/`.

## What this agent does

Classifies RPG images dropped in `.knowledge-base/00-Inbox/` (any subfolder, not just `images/`) using a local Qwen3-VL vision model served by LM Studio, then:
1. Detects image type: `portrait` / `body` / `battlemap` / `scene` / `token`
2. Renames the image in-place to a canonical slug (`{ancestry}-{class}-{element}.{type}` for portrait/body/token, `{type}-{environment}` for battlemap/scene)
3. Writes a draft entity `.md` to `.knowledge-base/01-Processing/` with type-specific body content (`status: draft`, `quality: 0`, `reviewed: false` — always)
4. For token PNGs (≥2 transparent corners), attempts face-match against other classified images in the same folder via cosine similarity on a center-crop grayscale vector (PIL + numpy only, no ML deps) and inherits the matched portrait's metadata instead of re-calling the LLM
5. Emits an `image-classified` signal for the downstream Lore agent and updates `system/state/inbox-queue.json`
6. `classify_image_full()` (public — importable by other agents/system code; replaces the old single-call `_classify_one`) runs a bounded multi-cycle conversation per image, image held in context for up to 10 messages total: (1) the classify-image.txt prompt, seeding a free-form `candidate_tags` list from the LLM's own `visual_analysis` block (equipment/clothing/fantasy_features/environment_details arrays — `_extract_candidate_tags`); (2) a follow-up confirming image type + more tags; (3) a follow-up inferring `entity_type` (same 18-value taxonomy as the classification agent's `_ALLOWED_TYPES`) + more tags; (4) `refine_tags_with_library()` (also public, independently callable) aligns the running tag list against classification agent's `state/tag-library.json` (read-only here). Target: ≥6 tags + both categories set; per-cycle parse/LLM errors after cycle 1 degrade gracefully (keep prior values) rather than spend a message on a retry. Final `candidate_tags`/`entity_type` land in the note's frontmatter via `_write_draft` — see `agents/classification/CLAUDE.md` for the library side.

A second, independent tool (`tools/extract_text.py`) runs OCR-style text extraction over images already classified above: it asks Qwen3-VL whether an image contains any readable text (signage, banners, scrolls, engravings, letters), and if so appends a `## Text on Image` section to the matching draft in `01-Processing/` (matched via the draft's `source:` frontmatter field). It never classifies, renames, or touches any other frontmatter field — body append only.

Full contract (inputs/outputs/responsibilities/restrictions) is in `AGENT.md` frontmatter — read it before changing behavior, it's the source of truth, not this file.

## Commands

```powershell
# Run this agent once, standalone (bypasses runner scheduling)
python agents\vision\tools\classify_images.py

# Or via the shared runner (respects intervalSeconds / preconditions)
python -m nexus.runner --task vision-agent --force

# One-time migration for old short-body drafts in 01-Processing/ (safe to re-run)
python agents\vision\tools\backfill_short_drafts.py

# Extract text-on-image ("## Text on Image") for already-classified images
python agents\vision\tools\extract_text.py

# Relevant tests
pytest agents/tests -k vision
```

LM Studio must be running at `http://localhost:1234/v1`. Vision model is selected via `agents/registry.yaml` → `llm_endpoints.vision_llm.model` (`classify_images.py` reads it through `shared.loaders.load_vault_config()` at import time, falling back to `qwen3-vl-4b-instruct` if registry.yaml is missing/malformed). `agent.json`'s dispatch config is unrelated — it only governs `claude-code`/`lm-studio` dispatch of the agent process itself, not this script's internal vision LLM calls. If the LLM is offline, the batch aborts silently — no image is marked failed.

## Architecture within this folder

- `tools/classify_images.py` — the whole agent: state I/O, token detection, face-match, slug builders, per-type draft body generation, `main()` batch loop, the public `classify_image_full()`/`refine_tags_with_library()` multi-cycle classification functions, and the `TOOLS`/`call_tool()` agentic interface consumed by `agent.json`'s dispatch.
- `tools/backfill_short_drafts.py` — one-off migration importing body builders from `classify_images.py`; only rewrites drafts with `body_lines < 15`.
- `tools/extract_text.py` — OCR-style text extraction over already-classified images; appends `## Text on Image` to the matching draft. Own `TOOLS`/`call_tool()` agentic interface (`extract_image_text`, `run_batch`), own state file, own log.
- `prompts/system.md` — role/workflow instructions for `claude-code`/agentic dispatch, covering both `classify_images.py` (tool-call sequence: `list_pending_images` → `run_batch` → `write_log`) and `extract_text.py` (`extract_image_text` / `run_batch`).
- `prompts/classify-image.txt` — the raw prompt sent to the vision LLM per image; defines the JSON schema and full PF2e vocabulary the model must answer with (kept in sync with `shared/models.py` `PF2E_*` constants — update both together).
- `state/processed-images.json` — `{version, images: {sha256: entry}, pathIndex: {relpath: sha256}}`. Failed images are keyed `path:{relpath}` in `pathIndex` (no sha), so `_get_folder_candidates` filters them out by that prefix, not by a `status` field alone. Each entry also carries `candidate_tags` (list[str], possibly empty) — the free-form brainstorm harvested from that image's `visual_analysis`.
- `state/token-links.json` — token→source-portrait face-match links, keyed by token sha256.
- `state/text-extractions.json` — `{sha256: {path, hasText}}`, tracks which classified images `extract_text.py` has already checked so they aren't re-checked every run.
- `.agents/shared` and `.system/state` — junctions into `agents/shared/` (the `IVaultGuard`/`FrontmatterIO`/`LLMClient`/`Logger`/`SignalEmitter` interfaces from the root architecture) and `system/state/` respectively; imports resolve via `sys.path.insert(_AGENTS_DIR)` at the top of each tool script, not via these junctions.

## Conventions specific to this agent

- Batch size is fixed at 10 images per run; within a batch, non-PNG files are processed before PNG (tokens are typically PNG, so this pushes them last, after their source portraits are already classified and in `state`).
- Never mark an image `status: failed` on an LLM *connection* error (offline LM Studio) — only on repeated response/parsing errors after retries. Connection errors abort the whole batch; response errors fail just that one image and continue the batch.
- Generated token PNGs from the dashboard's `agents/token/` pipeline (tracked in `agents/token/state/generated-tokens.json`) are excluded from `_candidate_images` — they are derived artifacts, not new source images, and re-ingesting them causes filename-bump duplication.
- This agent inherits the vault-wide rule that only `01-Processing/` may be written for drafts; it must never touch `02-Library/`, and `reviewed`/approved `status` are human-only fields it must never set (see root `AGENTS.md` → Directory Rules / Metadata Standard).
