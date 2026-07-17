import { describe, it, expect } from 'vitest'
import { defaultImageUrl, imageUrl } from '../image'

describe('defaultImageUrl', () => {
  it('maps a known type to its /defaults/<type>.jpg', () => {
    expect(defaultImageUrl('npc')).toBe('/defaults/npc.jpg')
    expect(defaultImageUrl('battlemap')).toBe('/defaults/battlemap.jpg')
    expect(defaultImageUrl('scene')).toBe('/defaults/scene.jpg')
  })

  it('falls back to the generic lore.jpg for an unknown type', () => {
    expect(defaultImageUrl('not-a-real-type')).toBe('/defaults/lore.jpg')
  })

  it('falls back to the generic lore.jpg for null/undefined', () => {
    expect(defaultImageUrl(null)).toBe('/defaults/lore.jpg')
    expect(defaultImageUrl(undefined)).toBe('/defaults/lore.jpg')
  })
})

describe('imageUrl', () => {
  it('returns null for null/undefined/empty path', () => {
    expect(imageUrl(null)).toBeNull()
    expect(imageUrl(undefined)).toBeNull()
    expect(imageUrl('')).toBeNull()
  })

  it('builds the /api/image url for a plain path', () => {
    expect(imageUrl('.knowledge-base/00-Inbox/images/art.png')).toBe(
      '/api/image?path=.knowledge-base%2F00-Inbox%2Fimages%2Fart.png',
    )
  })

  it('appends &thumb=1 when thumb is requested', () => {
    expect(imageUrl('a.png', { thumb: true })).toBe('/api/image?path=a.png&thumb=1')
  })

  it('appends &v=<cacheBust> when provided', () => {
    expect(imageUrl('a.png', { cacheBust: '2026-07-17T00:00:00Z' })).toBe(
      '/api/image?path=a.png&v=2026-07-17T00%3A00%3A00Z',
    )
  })

  it('combines thumb and cacheBust', () => {
    expect(imageUrl('a.png', { thumb: true, cacheBust: 42 })).toBe('/api/image?path=a.png&thumb=1&v=42')
  })
})
