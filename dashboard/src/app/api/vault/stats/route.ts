import { NextResponse } from 'next/server'
import path from 'path'
import { VAULT_ROOT, countFiles, countAllFiles, readJson } from '@/lib/vault'
import type { VaultStats } from '@/lib/types'

export const dynamic = 'force-dynamic'

export async function GET() {
  const folders = {
    inbox:      countFiles(path.join(VAULT_ROOT, '00-Inbox')),
    processing: countFiles(path.join(VAULT_ROOT, '01-Processing')),
    library:    countFiles(path.join(VAULT_ROOT, '02-Library')),
    campaigns:  countFiles(path.join(VAULT_ROOT, '03-Campaigns')),
    assets:     countAllFiles(path.join(VAULT_ROOT, '05-Assets')),
    archive:    countFiles(path.join(VAULT_ROOT, '99-Archive')),
  }

  const processedImages = readJson<{ images?: Record<string, unknown> }>('processed-images.json', {})
  const imageEntries = Object.entries(processedImages.images ?? {})
  const classifiedCount = imageEntries.filter(([, v]) => (v as Record<string,string>)?.status === 'ok').length

  const genTokens = readJson<{ tokens?: Record<string, unknown> }>('generated-tokens.json', {})
  const tokenCount = Object.keys(genTokens.tokens ?? {}).length

  const processedNpcs = readJson<{ npcs?: Record<string, { status: string }> }>('processed-npcs.json', {})
  const npcEntries = Object.values(processedNpcs.npcs ?? {})
  const approvedNpcs = npcEntries.filter(n => n?.status === 'ok').length

  const stats: VaultStats = {
    folders,
    images: {
      total: imageEntries.length,
      classified: classifiedCount,
      withTokens: tokenCount,
    },
    npcs: { total: npcEntries.length, approved: approvedNpcs },
    growth: [],
  }

  return NextResponse.json(stats)
}
