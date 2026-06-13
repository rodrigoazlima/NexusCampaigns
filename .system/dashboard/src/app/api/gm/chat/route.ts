import Anthropic from '@anthropic-ai/sdk'
import fs from 'fs'
import path from 'path'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT, VAULT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    return NextResponse.json({ error: 'ANTHROPIC_API_KEY not configured' }, { status: 500 })
  }

  try {
    const body = await req.json() as {
      message: string
      agent: string
      context?: string
      save?: boolean
    }
    const { message, agent, context, save } = body

    if (!message || !agent) {
      return NextResponse.json({ error: 'message and agent required' }, { status: 400 })
    }

    // Try to load agent system prompt
    let systemPrompt =
      'You are a Dungeon Master knowledge assistant for a tabletop RPG campaign. ' +
      'Help with worldbuilding, NPC creation, locations, quests, factions, lore, and narrative. ' +
      'Be concise, creative, and specific to the context provided.'

    const promptCandidates = [
      path.join(PROJECT_ROOT, '.agents', agent, 'prompts', 'system.md'),
      path.join(PROJECT_ROOT, '.agents', agent, 'prompts', 'classify-image.txt'),
    ]

    for (const p of promptCandidates) {
      try {
        if (fs.existsSync(p)) {
          systemPrompt = fs.readFileSync(p, 'utf-8')
          break
        }
      } catch {
        // continue
      }
    }

    const userContent = message + (context ? '\n\nContext:\n' + context : '')

    const client = new Anthropic({ apiKey })
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 2048,
      system: systemPrompt,
      messages: [{ role: 'user', content: userContent }],
    })

    const responseText = response.content
      .filter((c) => c.type === 'text')
      .map((c) => (c as { type: 'text'; text: string }).text)
      .join('')

    if (save && responseText) {
      try {
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
        const outputPath = path.join(VAULT_ROOT, '01-Processing', `gm-custom-${timestamp}.md`)
        const today = new Date().toISOString().split('T')[0]
        const fileContent =
          `---\ntype: lore\nstatus: pending\ncreated: ${today}\ntags:\n  - gm-generated\n---\n\n${responseText}`
        fs.writeFileSync(outputPath, fileContent, 'utf-8')
      } catch {
        // ignore write failures — don't fail the response
      }
    }

    return NextResponse.json({
      role: 'assistant',
      content: responseText,
      timestamp: new Date().toISOString(),
      agent,
    })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
