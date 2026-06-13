import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

interface V1Model {
  id: string
  max_context_length?: number
  [key: string]: unknown
}

interface V0Model {
  id: string
  arch?: string
  quantization?: string
  state?: string
  type?: string
  max_context_length?: number
  context_length?: number
}

export interface LmStudioModelMeta {
  id: string
  contextLength: number | null
  arch: string | null
  quantization: string | null
  state: string | null
  type: string | null
}

function normalize(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]/g, '')
}

function matchV0(v1Id: string, v0Models: V0Model[]): V0Model | null {
  const exact = v0Models.find((m) => m.id === v1Id)
  if (exact) return exact
  const n = normalize(v1Id)
  return (
    v0Models.find((m) => {
      const segs = m.id.split('/')
      return segs.some((s) => {
        const ns = normalize(s)
        return ns.includes(n) || n.includes(ns)
      })
    }) ?? null
  )
}

async function fetchV0Models(host: string): Promise<V0Model[]> {
  const url = `${host}/api/v0/models`
  const res = await fetch(url, { signal: AbortSignal.timeout(5000) })
  if (!res.ok) return []
  const data = await res.json()
  return (data?.data ?? []) as V0Model[]
}

export async function GET(req: NextRequest) {
  const baseUrl = req.nextUrl.searchParams.get('baseUrl')
  if (!baseUrl) {
    return NextResponse.json({ error: 'baseUrl required' }, { status: 400 })
  }

  const v1Base = baseUrl.replace(/\/$/, '')
  const host = v1Base.replace(/\/v1$/, '')

  try {
    const v1Res = await fetch(`${v1Base}/models`, { signal: AbortSignal.timeout(15000) })
    if (!v1Res.ok) {
      return NextResponse.json({ error: `LM Studio returned ${v1Res.status}` }, { status: 502 })
    }
    const v1Data = await v1Res.json()
    const v1Models: V1Model[] = v1Data?.data ?? []

    // try to enrich with v0 metadata; silently ignore failures
    let v0Models: V0Model[] = []
    try {
      v0Models = await fetchV0Models(host)
    } catch {
      // v0 API unavailable — proceed with v1 data only
    }

    const enriched: LmStudioModelMeta[] = v1Models.map((v1) => {
      const v0 = matchV0(v1.id, v0Models)
      return {
        id: v1.id,
        contextLength: v0?.context_length ?? v0?.max_context_length ?? (v1.max_context_length as number | undefined) ?? null,
        arch: v0?.arch ?? null,
        quantization: v0?.quantization ?? null,
        state: v0?.state ?? null,
        type: v0?.type ?? null,
      }
    })

    return NextResponse.json({ data: enriched })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return NextResponse.json({ error: msg }, { status: 502 })
  }
}
