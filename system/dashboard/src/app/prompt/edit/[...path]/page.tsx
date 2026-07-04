import fs from 'fs'
import path from 'path'
import { notFound } from 'next/navigation'
import { PROJECT_ROOT } from '@/lib/vault'
import PromptEditorClient from '@/components/prompts/PromptEditorClient'

const AGENTS_DIR = path.resolve(path.join(PROJECT_ROOT, 'agents'))

export default async function EditPromptPage({
  params,
}: {
  params: Promise<{ path: string[] }>
}) {
  const { path: segments } = await params
  const abs = path.resolve(AGENTS_DIR, ...segments)

  if (!abs.startsWith(AGENTS_DIR + path.sep)) notFound()
  if (!abs.endsWith('.md')) notFound()

  const relPath = segments.join('/')
  const content = fs.existsSync(abs) ? fs.readFileSync(abs, 'utf-8') : ''

  return <PromptEditorClient relPath={relPath} initialContent={content} />
}
