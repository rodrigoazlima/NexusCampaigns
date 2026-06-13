import { NextRequest, NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { VAULT_ROOT, findMarkdownByIdentifier } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(
  _req: NextRequest,
  { params }: { params: { filename: string } }
) {
  const identifier = decodeURIComponent(params.filename)
  const srcPath = findMarkdownByIdentifier(identifier)

  if (!srcPath || !fs.existsSync(srcPath)) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }

  const raw = fs.readFileSync(srcPath, 'utf-8')
  const parsed = matter(raw)
  const filename = path.basename(srcPath, '.md')

  const updated = {
    ...parsed.data,
    status: 'approved',
    reviewed: true,
    updated: new Date().toISOString().split('T')[0],
  }

  const newContent = matter.stringify(parsed.content, updated)

  const libDir = path.join(VAULT_ROOT, '02-Library')
  if (!fs.existsSync(libDir)) fs.mkdirSync(libDir, { recursive: true })

  const dstPath = path.join(libDir, `${filename}.md`)
  fs.writeFileSync(dstPath, newContent, 'utf-8')
  fs.unlinkSync(srcPath)

  return NextResponse.json({ success: true, destination: `02-Library/${filename}.md` })
}
