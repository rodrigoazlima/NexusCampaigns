import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'
import type { PromptFile } from '@/lib/types'

export const dynamic = 'force-dynamic'

const AGENTS_DIR = path.resolve(path.join(PROJECT_ROOT, 'agents'))

function isSafe(abs: string): boolean {
  return abs.startsWith(AGENTS_DIR + path.sep) || abs === AGENTS_DIR
}

function scanMd(dir: string): PromptFile[] {
  const results: PromptFile[] = []
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return results
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      results.push(...scanMd(full))
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      const rel = path.relative(AGENTS_DIR, full).replace(/\\/g, '/')
      const agent = rel.split('/')[0]
      const stat = fs.statSync(full)
      results.push({
        path: rel,
        agent,
        filename: entry.name,
        sizeBytes: stat.size,
        modifiedAt: stat.mtime.toISOString(),
      })
    }
  }
  return results
}

export async function GET() {
  const files = scanMd(AGENTS_DIR)
  files.sort((a, b) => a.path.localeCompare(b.path))
  return NextResponse.json(files)
}

export async function POST(req: NextRequest) {
  try {
    const { relPath, content } = await req.json() as { relPath: string; content: string }
    if (!relPath || typeof relPath !== 'string') {
      return NextResponse.json({ error: 'relPath required' }, { status: 400 })
    }
    const abs = path.resolve(AGENTS_DIR, ...relPath.split('/'))
    if (!isSafe(abs)) {
      return NextResponse.json({ error: 'Forbidden path' }, { status: 403 })
    }
    if (!abs.endsWith('.md')) {
      return NextResponse.json({ error: 'Only .md files allowed' }, { status: 400 })
    }
    if (fs.existsSync(abs)) {
      return NextResponse.json({ error: 'File already exists' }, { status: 409 })
    }
    fs.mkdirSync(path.dirname(abs), { recursive: true })
    fs.writeFileSync(abs, content ?? '', 'utf-8')
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
