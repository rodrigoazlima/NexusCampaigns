import { NextRequest, NextResponse } from 'next/server'
import { readAgents, readAgentSandbox, writeAgentSandbox } from '@/lib/vault'

export const dynamic = 'force-dynamic'

type Ctx = { params: Promise<{ agent: string }> }

function knownAgent(agent: string): boolean {
  return readAgents().some((a) => a.name === agent)
}

export async function GET(_req: NextRequest, { params }: Ctx) {
  const { agent } = await params
  if (!knownAgent(agent)) return NextResponse.json({ error: 'Unknown agent' }, { status: 404 })
  return NextResponse.json(readAgentSandbox(agent))
}

export async function PUT(req: NextRequest, { params }: Ctx) {
  const { agent } = await params
  if (!knownAgent(agent)) return NextResponse.json({ error: 'Unknown agent' }, { status: 404 })
  try {
    const body = (await req.json()) as { enabled?: unknown; allowDeletes?: unknown }
    if (typeof body.enabled !== 'boolean' || typeof body.allowDeletes !== 'boolean') {
      return NextResponse.json({ error: 'enabled and allowDeletes must be booleans' }, { status: 400 })
    }
    writeAgentSandbox(agent, { enabled: body.enabled, allowDeletes: body.allowDeletes })
    return NextResponse.json({ ok: true })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
