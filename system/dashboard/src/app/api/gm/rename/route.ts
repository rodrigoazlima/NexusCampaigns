import fs from 'fs'
import path from 'path'
import matter from 'gray-matter'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, VAULT_ROOT, writeFrontmatter } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { filename: string; newSlug: string }
    const { filename, newSlug } = body

    if (!filename || !newSlug) {
      return NextResponse.json({ error: 'filename and newSlug required' }, { status: 400 })
    }

    const cleanSlug = newSlug.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '')
    if (!cleanSlug) {
      return NextResponse.json({ error: 'Invalid slug' }, { status: 400 })
    }

    const newFilename = `${cleanSlug}.md`
    const srcPath = path.join(VAULT_ROOT, '01-Processing', filename)
    const destPath = path.join(VAULT_ROOT, '01-Processing', newFilename)

    if (!fs.existsSync(srcPath)) {
      return NextResponse.json({ error: 'File not found' }, { status: 404 })
    }
    if (filename !== newFilename && fs.existsSync(destPath)) {
      return NextResponse.json({ error: 'Target filename already exists' }, { status: 409 })
    }

    // Read source files before rename
    const raw = fs.readFileSync(srcPath, 'utf-8')
    const { data } = matter(raw)
    const sourceFiles: string[] = Array.isArray(data.source) ? data.source : []

    // Update id in frontmatter, then rename .md
    const today = new Date().toISOString().split('T')[0]
    writeFrontmatter(srcPath, { id: cleanSlug, updated: today })
    if (filename !== newFilename) {
      fs.renameSync(srcPath, destPath)
    }

    let newImagePath: string | null = null

    if (sourceFiles.length > 0) {
      // source[0] is already project-relative (e.g. ".knowledge-base/00-Inbox/RAW/clipart/x.webp"),
      // not a bare filename under 00-Inbox - renaming must preserve its subfolder.
      const sourceFile = sourceFiles[0]
      const oldImageAbs = path.join(PROJECT_ROOT, sourceFile)

      if (fs.existsSync(oldImageAbs)) {
        const ext = path.extname(sourceFile)
        const newImageFilename = `${cleanSlug}${ext}`
        const newImageAbs = path.join(path.dirname(oldImageAbs), newImageFilename)

        if (oldImageAbs !== newImageAbs) {
          fs.renameSync(oldImageAbs, newImageAbs)
        }

        const oldRelPath = sourceFile.replace(/\\/g, '/')
        const newRelPath = path.relative(PROJECT_ROOT, newImageAbs).replace(/\\/g, '/')
        newImagePath = newRelPath

        // Update inbox-queue.json key
        const queuePath = path.join(PROJECT_ROOT, 'system', 'state', 'inbox-queue.json')
        if (fs.existsSync(queuePath)) {
          const queue = JSON.parse(fs.readFileSync(queuePath, 'utf-8'))
          if (queue[oldRelPath] !== undefined) {
            queue[newRelPath] = queue[oldRelPath]
            delete queue[oldRelPath]
            fs.writeFileSync(queuePath, JSON.stringify(queue, null, 2), 'utf-8')
          }
        }

        // Update processed-images.json pathIndex
        const visionPath = path.join(PROJECT_ROOT, 'agents', 'vision', 'state', 'processed-images.json')
        if (fs.existsSync(visionPath)) {
          const visionState = JSON.parse(fs.readFileSync(visionPath, 'utf-8'))
          const idx = visionState.pathIndex ?? {}
          if (idx[oldRelPath] !== undefined) {
            idx[newRelPath] = idx[oldRelPath]
            delete idx[oldRelPath]
            // Also update path field on the image entry
            const sha = idx[newRelPath]
            if (sha && visionState.images?.[sha]) {
              visionState.images[sha].path = newRelPath
            }
            visionState.pathIndex = idx
            fs.writeFileSync(visionPath, JSON.stringify(visionState, null, 2), 'utf-8')
          }
        }

        // Update source field in the renamed .md
        writeFrontmatter(destPath, { source: [newRelPath], updated: today })
      }
    }

    return NextResponse.json({ ok: true, newFilename, newImagePath })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
