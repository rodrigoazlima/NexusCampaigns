import { NextResponse } from 'next/server'
import path from 'path'
import { VAULT_ROOT, countFiles, countAllFiles, readJson, scanDirectory } from '@/lib/vault'
import type { PipelineStats } from '@/lib/types'

export const dynamic = 'force-dynamic'

export async function GET() {
  const processingDir  = path.join(VAULT_ROOT, '01-Processing')
  const processingFiles = scanDirectory(processingDir)
  const pendingReview = processingFiles.filter(f => !f.fm.reviewed || f.fm.status === 'draft').length

  const processedImages = readJson<{ images?: Record<string, { status?: string }> }>('processed-images.json', {})
  const classifiedImages = Object.values(processedImages.images ?? {}).filter(v => v?.status === 'ok').length

  const processedNpcs = readJson<{ npcs?: Record<string, { status?: string }> }>('processed-npcs.json', {})
  const generatedNpcs = Object.values(processedNpcs.npcs ?? {}).filter(v => v?.status === 'ok').length

  const logs24h = (await import('@/lib/vault').then(m => m.parseLogSince(24)))
  const flow24h = logs24h.filter(l =>
    l.message.includes('--- DONE') || l.message.includes('Created') || l.message.includes('Wrote')
  ).length

  const stats: PipelineStats = {
    stages: [
      { id: 'inbox',      name: '00-Inbox',       folder: '00-Inbox',       count: countAllFiles(path.join(VAULT_ROOT, '00-Inbox')),      icon: '📥', color: '#6b7280' },
      { id: 'processing', name: '01-Processing',   folder: '01-Processing',  count: countFiles(path.join(VAULT_ROOT, '01-Processing')),    icon: '⚙️', color: '#0C5CAB' },
      { id: 'review',     name: 'Pending Review',  folder: '01-Processing',  count: pendingReview,                                         icon: '👁️', color: '#f59e0b' },
      { id: 'library',    name: '02-Library',      folder: '02-Library',     count: countFiles(path.join(VAULT_ROOT, '02-Library')),       icon: '📚', color: '#10b981' },
      { id: 'campaigns',  name: '03-Campaigns',    folder: '03-Campaigns',   count: countFiles(path.join(VAULT_ROOT, '03-Campaigns')),     icon: '⚔️', color: '#8b5cf6' },
    ],
    inboxImages: classifiedImages,
    processedItems: processingFiles.length,
    libraryEntities: countFiles(path.join(VAULT_ROOT, '02-Library')),
    pendingReview,
    totalFlow24h: flow24h,
  }

  return NextResponse.json(stats)
}
