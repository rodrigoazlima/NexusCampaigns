import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const baseUrl = req.nextUrl.searchParams.get('baseUrl')
  if (!baseUrl) {
    return NextResponse.json({ error: 'baseUrl required' }, { status: 400 })
  }

  try {
    const url = `${baseUrl.replace(/\/$/, '')}/models`
    const res = await fetch(url, { signal: AbortSignal.timeout(15000) })
    if (!res.ok) {
      return NextResponse.json({ error: `LM Studio returned ${res.status}` }, { status: 502 })
    }
    const data = await res.json()
    return NextResponse.json(data)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 502 })
  }
}
