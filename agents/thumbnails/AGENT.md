# Thumbnails Agent

Pre-generates small webp thumbnails for inbox images so the dashboard gallery
(`/gm/inbox`, queue views) loads kilobyte thumbs instead of full-resolution art.
No LLM calls. No vault writes.

## Inputs
- `system/state/inbox-queue.json` (read-only) — the set of images to thumbnail
- `.knowledge-base/00-Inbox/**` image files (read-only)

## Outputs
- `system/state/thumbs/<sha1(queue-path)>.webp` — 320px-wide webp, quality 80,
  keyed by sha1 of the queue key normalized to forward slashes. Served by the
  dashboard's `/api/image?path=...&thumb=1` route (falls back to the original
  when a thumb is missing).
- `agents/thumbnails/state/logs/` — per-task daily logs + shared automation.log

## Behavior
- Incremental: existing thumbs skipped; orphan thumbs (queue entry gone) pruned.
- Per-image failures logged and skipped, never fatal.
- Raster formats only (`.jpg .jpeg .png .webp .gif .bmp`); `.svg` skipped.

## Restrictions
- Never writes to the vault (`.knowledge-base/`).
- Never deletes anything outside `system/state/thumbs/`.
- No LLM, no network.
- No auto-commit — this agent has no `commit_scope` (all outputs are gitignored state).
