import { notFound } from 'next/navigation'
import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { ReviewEditor } from './ReviewEditor'
import { findMarkdownByIdentifier, readTasks, VAULT_ROOT } from '@/lib/vault'
import type { ReviewItem, ReviewStatus } from '@/lib/types'

export const dynamic = 'force-dynamic'

function readImageIndicesLocal(): {
  bySha256: Record<string, { path: string }>
  tokenBySha256: Record<string, string>
} {
  const AUTO_DIR = path.join(VAULT_ROOT, '.system')
  function readJ<T>(rel: string, fb: T): T {
    try { return JSON.parse(fs.readFileSync(path.join(AUTO_DIR, rel), 'utf-8').replace(/^﻿/, '')) as T }
    catch { return fb }
  }

  const processed = readJ<{
    version?: number
    images: Record<string, { sha256?: string; path?: string; status?: string }>
    pathIndex?: Record<string, string>
  }>('processed-images.json', { images: {} })

  const bySha256: Record<string, { path: string }> = {}
  const pathToSha256: Record<string, string> = {}
  const version = processed.version ?? 1

  if (version >= 2 && processed.pathIndex) {
    for (const [sha256, entry] of Object.entries(processed.images)) {
      if (/^[0-9a-f]{64}$/i.test(sha256) && entry.path) {
        bySha256[sha256] = { path: entry.path }
        pathToSha256[entry.path] = sha256
      }
    }
    Object.assign(pathToSha256, processed.pathIndex)
  } else {
    for (const [imgPath, entry] of Object.entries(processed.images)) {
      if (entry.sha256 && entry.status === 'ok') {
        bySha256[entry.sha256] = { path: imgPath }
        pathToSha256[imgPath] = entry.sha256
      }
    }
  }

  const genTokens = readJ<{
    version?: number
    tokens: Record<string, { token?: string; tokenPath?: string }>
  }>('generated-tokens.json', { tokens: {} })

  const tokenBySha256: Record<string, string> = {}
  if ((genTokens.version ?? 1) >= 2) {
    for (const [sha256, entry] of Object.entries(genTokens.tokens)) {
      const tp = entry.tokenPath ?? entry.token
      if (tp) tokenBySha256[sha256] = tp
    }
  } else {
    for (const [imgPath, entry] of Object.entries(genTokens.tokens)) {
      const tp = entry.token
      if (!tp) continue
      const normPath = imgPath.replace(/\//g, '\\')
      const sha256 = pathToSha256[normPath] ?? pathToSha256[imgPath]
      if (sha256) tokenBySha256[sha256] = tp
    }
  }

  return { bySha256, tokenBySha256 }
}

interface Props {
  params: { filename: string }
}

export default function ReviewDetailPage({ params }: Props) {
  const identifier = decodeURIComponent(params.filename)
  const filePath = findMarkdownByIdentifier(identifier)

  if (!filePath || !fs.existsSync(filePath)) notFound()

  const raw = fs.readFileSync(filePath, 'utf-8')
  const { data: fm, content: body } = matter(raw)
  const filename = path.basename(filePath, '.md')

  const rels = Array.isArray(fm.relationships) ? fm.relationships : []
  const sources: string[] = Array.isArray(fm.source) ? fm.source : (fm.source ? [String(fm.source)] : [])
  const sha256: string | null = typeof fm.sha256 === 'string' ? fm.sha256 : null

  const { bySha256, tokenBySha256 } = readImageIndicesLocal()

  let imageUrl: string | null = null
  let tokenUrl: string | null = null

  if (sha256 && bySha256[sha256]) {
    const imgRelPath = bySha256[sha256].path
    imageUrl = `/api/image?path=${encodeURIComponent('/' + imgRelPath.replace(/\\/g, '/'))}`
    const tokenRelPath = tokenBySha256[sha256]
    if (tokenRelPath) tokenUrl = `/api/image?path=${encodeURIComponent('/' + tokenRelPath.replace(/\\/g, '/'))}`
  }

  const item: ReviewItem = {
    path: `01-Processing/${filename}.md`,
    filename,
    id: typeof fm.id === 'string' ? fm.id : filename,
    sha256,
    type: typeof fm.type === 'string' ? fm.type : 'unknown',
    status: (['draft', 'review', 'approved', 'archived'].includes(fm.status) ? fm.status : 'draft') as ReviewStatus,
    quality: typeof fm.quality === 'number' ? fm.quality : 0,
    suggestedQuality: typeof fm.suggestedQuality === 'number' ? fm.suggestedQuality : null,
    tags: Array.isArray(fm.tags) ? fm.tags.map(String) : [],
    source: sources,
    reviewed: Boolean(fm.reviewed),
    relationships: rels.map(String),
    hasRelationships: rels.length > 0,
    isOrphan: rels.length === 0 && !body.includes('[['),
    createdAt: typeof fm.created === 'string' ? fm.created : '',
    updatedAt: typeof fm.updated === 'string' ? fm.updated : '',
    description: '',
    imageUrl,
    tokenUrl,
    agentNotes: (fm.agent_notes && typeof fm.agent_notes === 'object') ? fm.agent_notes as Record<string, string> : {},
  }

  const agents = readTasks().map(t => ({ id: t.id, description: t.description }))

  return <ReviewEditor item={item} body={body} agents={agents} />
}
