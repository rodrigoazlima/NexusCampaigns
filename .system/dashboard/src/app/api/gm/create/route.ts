import { NextRequest, NextResponse } from 'next/server'
import { createDraft } from '@/lib/vault'

export const dynamic = 'force-dynamic'

// Body skeleton per type — pre-fills the editor's structured sections.
// Only the cast pillar (npc/character) is wired this phase; other pillars add
// their skeleton when their page lands.
const NPC_SKELETON = `## Identity
- **Role / occupation:**
- **Appearance hook:**
- **Voice / mannerism:**

## Want
> What they want from the party or the world — the engine of every scene.

## Secret
> Something the party can discover that changes how they see them.

## Personality
- One line:

## Ties
- **Faction:** [[ ]]
- **Location:** [[ ]]
- **Offers the party:** hook / info / threat

## Related
`

const SKELETONS: Record<string, string> = {
  npc: NPC_SKELETON,
  character: NPC_SKELETON,
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export async function POST(req: NextRequest) {
  try {
    const { type, name } = (await req.json()) as { type?: string; name?: string }

    if (!type || !SKELETONS[type]) {
      return NextResponse.json({ error: 'unsupported or missing type' }, { status: 400 })
    }

    const slug = name ? slugify(name) : ''
    const id = slug ? `${type}-${slug}` : `${type}-untitled-${Date.now().toString(36)}`

    const filename = createDraft({ id, type, body: SKELETONS[type] })

    return NextResponse.json({ ok: true, id, filename })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}
