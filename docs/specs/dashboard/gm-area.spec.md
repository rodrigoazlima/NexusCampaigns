# Game Master Area - Product Specification

**Version:** 1.0
**Date:** 2026-06-13
**Part of:** `docs/specs/dashboard/dashboard.spec.md` (implementation: `docs/specs/dashboard/admin-dashboard.spec.md`)

---

## 1. Purpose

The Game Master Area is the human-in-the-loop interface of the Nexus Campaigns. It gives the GM direct control over the AI pipeline: reviewing AI-generated content, approving or rejecting drafts, managing images and tokens, and sending custom instructions to agents.

The existing dashboard pages are read-only monitoring tools. The GM Area adds **write operations**: approval, rejection, flagging, field editing, and agent chat.

---

## 2. Pages

| Route | Page | Description |
|-------|------|-------------|
| `/gm` | GM Hub | Pending count, quick-action cards, recent decisions |
| `/gm/review` | Review Queue | Image + draft side-by-side, approve/reject/flag per card |
| `/gm/inbox` | Inbox Gallery | All 00-Inbox files with queue status, agent progress |
| `/gm/tokens` | Token Gallery | Generated tokens + frame browser |
| `/gm/chat` | Agent Chat | Freeform instructions to lore/wiki/vision agents |

---

## 3. Navigation (Sidebar)

Added above OVERVIEW section:

```
GAME MASTER
  🎲  GM Hub      /gm
  ✅  Review      /gm/review
  🖼  Inbox       /gm/inbox
  ⭕  Tokens      /gm/tokens
  💬  Chat        /gm/chat
──────────────────────
OVERVIEW
  ...
```

---

## 4. Information Architecture

### GM Hub `/gm`

Quick-status landing page. Answers: "What do I need to do right now?"

- KPI row: Pending Review · High Quality (≥7) · Approved Today · Inbox Depth
- Action cards: large touch-friendly cards → Review Queue / Inbox / Tokens / Chat
- Recent decisions feed: last 10 approve/reject/flag actions (from a local decisions log)
- Agent status strip: compact 1-line status per active agent

---

### Review Queue `/gm/review`

Card-per-draft layout. Each card shows:

**Left panel (image):**
- Source image from `00-Inbox/images/` (via `/api/image?path=`)
- Token preview (if generated)
- Enlarge button → full-screen ImageModal

**Right panel (draft):**
- Entity id, type badge, status badge
- Full markdown content (rendered)
- Frontmatter fields: tags, relationships, source files
- QualityPicker (1-10 button grid)
- GMActionBar: Approve · Reject · Flag · Chat

**Filtering (top bar):**
- By type: all / npc / location / faction / quest / creature / item / lore
- By status: all / draft / review / approved
- By quality: all / high (≥7) / medium (4-6) / low (<4)
- Sort: quality desc / created desc / alphabetical

**Approve action:**
1. GM selects quality score (required)
2. Clicks Approve
3. POST `/api/gm/approve` → sets `status: approved, reviewed: true, quality: N, updated: today`
4. File promoted to `02-Library/`
5. Card collapses with success toast

**Reject action:**
1. Clicks Reject (optional reason text)
2. POST `/api/gm/reject` → sets `status: rejected, quality: 1`
3. Card shows rejected state (dim, strikethrough)

**Flag for reprocessing:**
1. Clicks Flag
2. POST `/api/gm/flag` → sets `needs_reprocessing: true`
3. Agents will re-process on next run

**Chat from card:**
1. Clicks Chat → opens chat panel within card
2. GM types custom instruction ("Make this NPC more sinister, add a dark secret")
3. POST `/api/gm/chat` with agent=lore, context={entity id, current draft}
4. Response rendered as markdown below
5. Accept response → POST `/api/gm/edit` to merge into frontmatter

---

### Inbox Gallery `/gm/inbox`

Grid of all files in `00-Inbox/` with their processing status.

Per card:
- Image thumbnail (images) or file icon (docs)
- Filename + ingested-at age
- Agent slots: vision · lore · classification · wiki (color-coded pending/done/skip/error)
- Token badge: whether a token was generated
- "Re-trigger" button → POST `/api/gm/flag` on associated draft

Sort: newest first, stuck items (all agents pending for >24h) at top with danger border.

---

### Token Gallery `/gm/tokens`

Two panels:

**Generated Tokens panel:**
- Grid of `*-token.png` files from `00-Inbox/images/` subfolders
- Preview of token
- Associated entity name
- Approve button → move to `05-Assets/tokens/{entity-id}-token.png`

**Token Frames panel:**
- Grid of all frames from `05-Assets/tokens/frames/`
- Click frame → preview how it would look with a random token

---

### Agent Chat `/gm/chat`

Full chat interface with persistent history per session.

**Header:**
- Agent selector: lore · wiki · vision · classification (dropdown)
- Model indicator (from registry.yaml)
- Clear history button

**Chat area:**
- Scrollable message list
- User messages: right-aligned, primary accent
- Agent responses: left-aligned, surface-1 panel, markdown rendered
- Timestamps on each message

**Input area:**
- Textarea (expandable)
- Context attach: image path, entity file, or free text
- Send button (or Enter)
- Optional `--save` flag → saves agent response to `01-Processing/` as new draft

**Behavior:**
- POST `/api/gm/chat` with `{message, agent, context?, save?}`
- Agent's system.md used as system prompt
- Response streamed back (SSE or buffered)
- History stored in `dashboard/.gm-chat-history.json` (session-local, not in vault)

---

## 5. API Routes

All routes: `export const dynamic = 'force-dynamic'`. Write routes: `POST`.

| Method | Route | Body | Returns |
|--------|-------|------|---------|
| GET | `/api/gm/inbox` | - | `InboxImage[]` |
| GET | `/api/gm/tokens` | - | `{ tokens: TokenFile[], frames: string[] }` |
| POST | `/api/gm/approve` | `{ filename, quality }` | `{ ok, promoted }` |
| POST | `/api/gm/reject` | `{ filename, reason? }` | `{ ok }` |
| POST | `/api/gm/flag` | `{ filename }` | `{ ok }` |
| POST | `/api/gm/edit` | `{ filename, fields }` | `{ ok }` |
| POST | `/api/gm/chat` | `{ message, agent, context?, save? }` | `{ role, content, timestamp }` |

---

## 6. Data Model Additions

```typescript
interface InboxImage {
  path: string              // relative to PROJECT_ROOT
  filename: string
  type: 'image' | 'document' | 'other'
  ingestedAt: string
  agentSlots: Record<string, 'pending' | 'done' | 'skip' | 'error'>
  hasToken: boolean
  tokenPath: string | null
  isStuck: boolean
}

interface TokenFile {
  path: string
  filename: string
  entityId: string | null   // derived from filename slug
  generatedAt: string | null
}

interface GMChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  agent: string
}
```

---

## 7. Write Operations (vault.ts)

```typescript
// Update frontmatter fields in-place
writeFrontmatter(filepath: string, updates: Record<string, unknown>): void

// Copy from 01-Processing/ to 02-Library/ with updated metadata
promoteToLibrary(srcFilepath: string, targetFilename: string): void

// Read inbox items with queue status
readInboxImages(): InboxImage[]

// Read token files from assets + inbox
readTokenFiles(): { tokens: TokenFile[], frames: string[] }
```

Encoding: UTF-8. Uses `gray-matter` + `matter.stringify`. Atomic write pattern: write to temp then rename.

---

## 8. Approve Logic (Critical Path)

```
Preconditions:
  - File exists in 01-Processing/
  - quality is 1-10 (integer)

Steps:
  1. Read file content
  2. Parse frontmatter with gray-matter
  3. Merge updates: { status: 'approved', reviewed: true, quality, updated: YYYY-MM-DD }
  4. Stringify: matter.stringify(content, mergedData)
  5. Write back to 01-Processing/{filename}   ← update in place
  6. Copy to 02-Library/{filename}            ← promote
  7. Return { ok: true, promoted: true }

Note: File stays in 01-Processing/ AND appears in 02-Library/. Human manually
removes from Processing when ready (canon rule: never auto-delete).
```

---

## 9. Agent Chat Architecture

```
GM types message → POST /api/gm/chat
  → Read agents/{agent}/prompts/system.md as system prompt
  → Append user message
  → POST to Anthropic API (claude-haiku-4-5-20251001)
  → Return assistant response
  → If save=true: write to 01-Processing/{slug}-custom-{timestamp}.md
```

Env var: `ANTHROPIC_API_KEY` in `system/dashboard/.env.local`.
Fallback: if key missing, return `{ error: 'ANTHROPIC_API_KEY not set' }`.

Agent system prompts already exist at:
- `agents/lore/prompts/system.md`
- `agents/wiki/prompts/system.md`
- `agents/vision/prompts/classify-step1-type.txt` (+ `classify-step2-visual.txt`, `classify-step3-pf2e-{character,environment}.txt`, `classify-step4-description.txt`)
- `agents/classification/prompts/system.md`

---

## 10. Component Inventory

| Component | File | Purpose |
|-----------|------|---------|
| `ImageModal` | `gm/ImageModal.tsx` | Full-screen image overlay with close/zoom |
| `QualityPicker` | `gm/QualityPicker.tsx` | 1-10 buttons, danger/warning/success zones |
| `GMActionBar` | `gm/GMActionBar.tsx` | Approve · Reject · Flag · Chat buttons |
| `InboxImageCard` | `gm/InboxImageCard.tsx` | Image + agent slot badges + age |
| `TokenCard` | `gm/TokenCard.tsx` | Token PNG + entity label + approve action |
| `ReviewCard` | `gm/ReviewCard.tsx` | Full review card (image+draft+actions) |
| `ChatMessage` | `gm/ChatMessage.tsx` | Single chat bubble (user or assistant) |

---

## 11. Implementation Phases

### Phase 1 - MVP (this PR)
- [x] Spec file written
- [ ] vault.ts: `writeFrontmatter`, `promoteToLibrary`, `readInboxImages`, `readTokenFiles`
- [ ] types.ts: `InboxImage`, `TokenFile`, `GMChatMessage`
- [ ] API: approve, reject, flag, edit, inbox GET, tokens GET
- [ ] API: chat (Anthropic)
- [ ] Pages: /gm, /gm/review, /gm/inbox, /gm/tokens, /gm/chat
- [ ] Components: all 7
- [ ] Sidebar: GM section
- [ ] Spec updated post-implementation

### Phase 2 - Enhanced
- [ ] Streaming chat responses (SSE)
- [ ] Bulk approve/reject (select all high-quality)
- [ ] Inline relationship editor (add wikilinks visually)
- [ ] Image comparison (before/after reprocessing)
- [ ] Tag autocomplete from 02-Library/ tag corpus
- [ ] Keyboard shortcuts (j/k navigation, a=approve, r=reject, f=flag)

### Phase 3 - Advanced
- [ ] Drag-and-drop inbox upload
- [ ] Custom scenario builder (edit scenarios.json via UI)
- [ ] Token frame selector (choose frame per NPC)
- [ ] Campaign session notes editor
- [ ] Export approved entities as PDF session handout
