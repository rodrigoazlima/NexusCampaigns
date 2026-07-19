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

// Mirrors the MIME map in src/app/api/image/route.ts. `source`/`tokenPath`
// can point at non-image files (e.g. a lore entry sourced from a .md doc) -
// filtering here skips a doomed /api/image round-trip instead of depending
// on the <img> onError handler, which can miss a same-tick SSR failure
// (fs-read 404 resolves before React hydration attaches the listener).
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.svg'])

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
  const ext = path.slice(path.lastIndexOf('.')).toLowerCase()
  if (!IMAGE_EXTENSIONS.has(ext)) return null
  let url = `/api/image?path=${encodeURIComponent(path)}`
  if (opts?.thumb) url += '&thumb=1'
  if (opts?.cacheBust) url += `&v=${encodeURIComponent(opts.cacheBust)}`
  return url
}
