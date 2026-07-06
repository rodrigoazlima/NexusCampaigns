# Thumbnails Agent

You maintain the pre-generated thumbnail cache for the dashboard inbox gallery.

This agent runs as a plain CLI script (`tools/thumbnails_agent.py`) with no LLM
dispatch. If you are reading this as an LLM, the only correct action is to run
the script; there are no decisions to make.

## Workflow
1. Read `system/state/inbox-queue.json`.
2. For each image entry without a thumb in `system/state/thumbs/`, generate a
   320px-wide webp (quality 80) named `<sha1(normalized queue path)>.webp`.
3. Prune thumbs whose queue entry no longer exists.
4. Log `--- START ---` / `--- DONE ---` with generated/failed counts.

## Success criteria
- Every raster image in the queue has a matching thumb file.
- No files written outside `system/state/thumbs/` and the agent's own state/logs.
