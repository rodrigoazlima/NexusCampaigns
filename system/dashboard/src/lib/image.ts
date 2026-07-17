// Known /defaults/<name>.jpg assets (public/defaults/). Mirrors the 20 files
// documented in docs/defaults/prompts/README.md - the 18 allowed vault entity
// `type:` values plus the two image-classification roles (battlemap, scene).
// ponytail: hand-listed, not derived from lib/pillars.ts - a type here must
// have a matching shipped jpg, and pillars.ts doesn't guarantee that.
const DEFAULT_IMAGE_TYPES = new Set([
  'artifact', 'battlemap', 'character', 'city', 'creature', 'dungeon',
  'encounter', 'event', 'faction', 'item', 'location', 'lore', 'monster',
  'npc', 'organization', 'quest', 'religion', 'scene', 'timeline', 'village',
])

const GENERIC_DEFAULT = '/defaults/lore.jpg'

/** Per-type placeholder for a missing/failed vault image. Unknown or absent
 *  type (e.g. pre-classification queue/inbox items) falls back to the
 *  generic "lore" icon. */
export function defaultImageUrl(type?: string | null): string {
  return type && DEFAULT_IMAGE_TYPES.has(type) ? `/defaults/${type}.jpg` : GENERIC_DEFAULT
}

/** Builds the /api/image URL for a vault-relative (or absolute) path.
 *  Returns null when there's no path, so callers/VaultImage can skip
 *  straight to the default instead of doing a doomed round-trip. */
export function imageUrl(
  path: string | null | undefined,
  opts?: { thumb?: boolean; cacheBust?: string | number | null },
): string | null {
  if (!path) return null
  let url = `/api/image?path=${encodeURIComponent(path)}`
  if (opts?.thumb) url += '&thumb=1'
  if (opts?.cacheBust) url += `&v=${encodeURIComponent(opts.cacheBust)}`
  return url
}
