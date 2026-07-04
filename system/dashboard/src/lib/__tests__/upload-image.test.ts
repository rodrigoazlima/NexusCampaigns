import { describe, it, expect, vi, beforeEach } from 'vitest'
import { uploadImage, enqueueImage, isImageFile } from '../upload-image'

function makeFile(name: string, type = 'image/png'): File {
  return new File(['x'], name, { type })
}

describe('isImageFile', () => {
  it('accepts .png', () => expect(isImageFile(makeFile('art.png'))).toBe(true))
  it('accepts .jpg', () => expect(isImageFile(makeFile('art.jpg'))).toBe(true))
  it('accepts .jpeg', () => expect(isImageFile(makeFile('art.jpeg'))).toBe(true))
  it('accepts .webp', () => expect(isImageFile(makeFile('art.webp'))).toBe(true))
  it('accepts .gif', () => expect(isImageFile(makeFile('art.gif'))).toBe(true))
  it('accepts .avif', () => expect(isImageFile(makeFile('art.avif'))).toBe(true))
  it('rejects .pdf', () => expect(isImageFile(makeFile('doc.pdf'))).toBe(false))
  it('rejects .exe', () => expect(isImageFile(makeFile('evil.exe'))).toBe(false))
  it('rejects .txt', () => expect(isImageFile(makeFile('note.txt'))).toBe(false))
  it('is case-insensitive', () => expect(isImageFile(makeFile('ART.PNG'))).toBe(true))
})

describe('uploadImage', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('posts to /api/gm/upload-image with file and default targetPath', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, path: 'knowledge-base/00-Inbox/images/art.png' }),
    } as Response)

    const file = makeFile('art.png')
    const result = await uploadImage({ file })

    expect(spy).toHaveBeenCalledOnce()
    const [url, init] = spy.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/gm/upload-image')
    expect(init.method).toBe('POST')

    const body = init.body as FormData
    expect(body.get('file')).toBe(file)
    expect(body.get('targetPath')).toBe('knowledge-base/00-Inbox/images/art.png')

    expect(result).toEqual({ ok: true, path: 'knowledge-base/00-Inbox/images/art.png' })
  })

  it('uses provided targetPath', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, path: 'custom/path.png' }),
    } as Response)

    await uploadImage({ file: makeFile('art.png'), targetPath: 'custom/path.png' })

    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit]
    expect((init.body as FormData).get('targetPath')).toBe('custom/path.png')
  })

  it('returns error when API returns error message', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: 'Unsupported extension: .exe' }),
    } as Response)

    const result = await uploadImage({ file: makeFile('evil.exe') })
    expect(result).toEqual({ ok: false, error: 'Unsupported extension: .exe' })
  })

  it('returns HTTP status when API error has no message', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    } as Response)

    const result = await uploadImage({ file: makeFile('art.png') })
    expect(result).toEqual({ ok: false, error: 'HTTP 500' })
  })

  it('returns error on network failure', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('Network error'))

    const result = await uploadImage({ file: makeFile('art.png') })
    expect(result).toEqual({ ok: false, error: 'Error: Network error' })
  })

  it('returns error when fetch throws a non-Error', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue('timeout')

    const result = await uploadImage({ file: makeFile('art.png') })
    expect(result).toEqual({ ok: false, error: 'timeout' })
  })
})

describe('enqueueImage', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('posts to /api/gm/queue/add with the vault path', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    } as Response)

    const result = await enqueueImage('knowledge-base/00-Inbox/images/art.png')

    expect(spy).toHaveBeenCalledOnce()
    const [url, init] = spy.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/gm/queue/add')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ path: 'knowledge-base/00-Inbox/images/art.png' })
    expect(result).toEqual({ ok: true, skipped: undefined })
  })

  it('returns skipped: true when already in queue', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, skipped: true }),
    } as Response)

    const result = await enqueueImage('knowledge-base/00-Inbox/images/art.png')
    expect(result).toEqual({ ok: true, skipped: true })
  })

  it('returns error on API failure', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: 'path must be under knowledge-base/00-Inbox/' }),
    } as Response)

    const result = await enqueueImage('evil/path.png')
    expect(result).toEqual({ ok: false, error: 'path must be under knowledge-base/00-Inbox/' })
  })

  it('returns error on network failure', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('Network error'))

    const result = await enqueueImage('knowledge-base/00-Inbox/images/art.png')
    expect(result).toEqual({ ok: false, error: 'Error: Network error' })
  })
})
