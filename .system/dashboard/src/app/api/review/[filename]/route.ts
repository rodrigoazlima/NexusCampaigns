import { NextRequest, NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { findMarkdownByIdentifier } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function PATCH(
  req: NextRequest,
  { params }: { params: { filename: string } }
) {
  const identifier = decodeURIComponent(params.filename)
  const filePath = findMarkdownByIdentifier(identifier)

  if (!filePath || !fs.existsSync(filePath)) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }

  const body = await req.json() as Record<string, unknown>
  const raw = fs.readFileSync(filePath, 'utf-8')
  const parsed = matter(raw)

  // Separate filename from frontmatter fields
  const { filename: newFilename, ...fmFields } = body

  const updated = {
    ...parsed.data,
    ...Object.fromEntries(Object.entries(fmFields).filter(([, v]) => v !== undefined)),
    updated: new Date().toISOString().split('T')[0],
  }

  const newContent = matter.stringify(parsed.content, updated)

  const currentFilename = path.basename(filePath, '.md')
  const targetFilename = typeof newFilename === 'string' && newFilename.trim()
    ? newFilename.trim()
    : currentFilename

  if (targetFilename !== currentFilename) {
    // Write updated frontmatter to current path first, then rename
    fs.writeFileSync(filePath, newContent, 'utf-8')
    const newPath = path.join(path.dirname(filePath), `${targetFilename}.md`)
    fs.renameSync(filePath, newPath)
    // Canonical identifier: sha256 if available, else new filename
    const newIdentifier = (updated as Record<string, unknown>).sha256 as string | undefined ?? targetFilename
    return NextResponse.json({ success: true, newIdentifier })
  }

  fs.writeFileSync(filePath, newContent, 'utf-8')
  return NextResponse.json({ success: true })
}
