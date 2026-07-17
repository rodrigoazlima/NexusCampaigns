import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

export interface ModelInfoResult {
  found: boolean
  contextLength: number | null
  arch: string | null
  quantization: string | null
  state: string | null
  type: string | null
  source: string | null   // which endpoint provided the data
}

type RawModel = Record<string, unknown>

function norm(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]/g, '')
}

function fuzzyMatch(modelId: string, candidates: RawModel[]): RawModel | null {
  // exact match first
  const exact = candidates.find((m) => m.id === modelId)
  if (exact) return exact

  const n = norm(modelId)
  if (!n) return null

  return (
    candidates.find((m) => {
      const rawId = String(m.id ?? '')
      // normalize full id
      if (norm(rawId).includes(n)) return true
      // normalize path segments (handles org/model-GGUF/file.gguf format)
      return rawId.split('/').some((seg) => {
        const ns = norm(seg)
        // require segment length > 4 to avoid matching trivial parts like 'q4'
        return ns.length > 4 && (ns.includes(n) || n.includes(ns))
      })
    }) ?? null
  )
}

function extractInfo(raw: RawModel, source: string): ModelInfoResult {
  const contextLength =
    (raw.context_length as number | undefined) ??
    (raw.max_context_length as number | undefined) ??
    null

  return {
    found: true,
    contextLength,
    arch: (raw.arch as string | undefined) ?? null,
    quantization: (raw.quantization as string | undefined) ?? null,
    state: (raw.state as string | undefined) ?? null,
    type: (raw.type as string | undefined) ?? null,
    source,
  }
}

async function tryEndpoint(url: string, modelId: string, source: string): Promise<ModelInfoResult | null> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(6000) })
    if (!res.ok) return null
    const data = await res.json()
    const list: RawModel[] = data?.data ?? (Array.isArray(data) ? data : [data])
    const match = fuzzyMatch(modelId, list)
    if (!match) return null
    return extractInfo(match, source)
  } catch {
    return null
  }
}

export async function GET(req: NextRequest) {
  const baseUrl = req.nextUrl.searchParams.get('baseUrl')
  const modelId = req.nextUrl.searchParams.get('modelId')

  if (!baseUrl || !modelId) {
    return NextResponse.json({ error: 'baseUrl and modelId required' }, { status: 400 })
  }

  // derive host - strip /v1 or /v1/ suffix
  const host = baseUrl.replace(/\/v1\/?$/, '').replace(/\/$/, '')
  const v1Base = baseUrl.replace(/\/+$/, '')

  // try in order of data quality
  const attempts: Array<[string, string]> = [
    [`${host}/api/v0/models/loaded`, 'v0/loaded'],
    [`${host}/api/v0/models`, 'v0/all'],
    [`${v1Base}/models`, 'v1/list'],
  ]

  for (const [url, source] of attempts) {
    const result = await tryEndpoint(url, modelId, source)
    if (result) return NextResponse.json(result)
  }

  return NextResponse.json({
    found: false,
    contextLength: null,
    arch: null,
    quantization: null,
    state: null,
    type: null,
    source: null,
  } satisfies ModelInfoResult)
}
