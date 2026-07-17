const ALLOWED_EXTS = new Set([
  '.jpg', '.jpeg', '.png', '.webp', '.gif',
  '.bmp', '.tiff', '.tif', '.avif', '.heic', '.heif', '.jfif',
])

export interface UploadImageOptions {
  file: File
  /** Relative to PROJECT_ROOT. Defaults to `.knowledge-base/00-Inbox/images/{file.name}` */
  targetPath?: string
}

export interface UploadImageResult {
  ok: boolean
  /** Server-relative path of the saved file (on success), or of the pre-existing match (on duplicate) */
  path?: string
  /** True if an identical image (by content hash) already exists in the vault - nothing was written */
  duplicate?: boolean
  /** Error message (on failure) */
  error?: string
}

export function isImageFile(file: File): boolean {
  const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase()
  return ALLOWED_EXTS.has(ext)
}

export interface EnqueueResult {
  ok: boolean
  skipped?: boolean
  error?: string
}

export async function enqueueImage(vaultPath: string): Promise<EnqueueResult> {
  try {
    const res = await fetch('/api/gm/queue/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: vaultPath }),
    })
    const json = await res.json()
    if (!res.ok) return { ok: false, error: json.error ?? `HTTP ${res.status}` }
    return { ok: true, skipped: json.skipped }
  } catch (err) {
    return { ok: false, error: String(err) }
  }
}

export async function uploadImage(options: UploadImageOptions): Promise<UploadImageResult> {
  const { file, targetPath = `.knowledge-base/00-Inbox/images/${file.name}` } = options

  const form = new FormData()
  form.append('file', file)
  form.append('targetPath', targetPath)

  try {
    const res = await fetch('/api/gm/upload-image', { method: 'POST', body: form })
    const json = await res.json()
    if (!res.ok) return { ok: false, error: json.error ?? `HTTP ${res.status}` }
    return { ok: true, path: json.path, duplicate: json.duplicate }
  } catch (err) {
    return { ok: false, error: String(err) }
  }
}
