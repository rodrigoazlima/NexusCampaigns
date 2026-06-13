import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}))
  const { baseUrl, modelId, temperature, maxTokens } = body as {
    baseUrl?: string
    modelId?: string
    temperature?: number
    maxTokens?: number
  }

  if (!baseUrl || !modelId) {
    return NextResponse.json({ error: 'baseUrl and modelId required' }, { status: 400 })
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/chat/completions`
  const payload = {
    model: modelId,
    messages: [
      { role: 'user', content: `hi — ${new Date().toISOString()}` },
    ],
    max_tokens: maxTokens ?? 128,
    temperature: temperature ?? 0,
    stream: false,
  }

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(30000),
    })

    const data = await res.json()

    if (!res.ok) {
      return NextResponse.json(
        { error: data?.error?.message ?? `HTTP ${res.status}` },
        { status: 502 }
      )
    }

    const reply = data?.choices?.[0]?.message?.content ?? null
    const usage = data?.usage ?? null

    return NextResponse.json({ ok: true, reply, usage })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 502 })
  }
}
