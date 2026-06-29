# Campaign Setting — Page Spec

**Route:** `/gm` (replaces the current "Campaign Workshop" hub)
**Icon:** `Dices` · **Nav:** GAME MASTER → Campaign
**Source guide:** `docs/campaign-setting-guide.md`

The command center for a whole campaign setting. Not an entity collection — it
is the **frame + progress + readiness** layer that sits over the six pillar
pages. A GM lands here to answer one question: *is my setting ready to run, and
what's the next thing to build?*

---

## 1. Concept

A campaign setting is "ready to run not when it's finished, but when it has one
place, a handful of people who want conflicting things, and a reason the party
can't sit still" (the guide's rule of thumb). This page operationalizes the
guide's 8 sections:

- **§0 Frame** — the decisions (pitch, tone, scale, tension, buy-in).
- **§1–6 Pillars** — progress per domain, deep-linking to the pillar pages.
- **§7 Wiring** — relationship-web health (orphans, triangles).
- **§8 Readiness** — the go/no-go checklist, computed from real vault state.

---

## 2. Layout

```
┌ PageHeader: Dices · "Campaign Setting" · "{frame.pitch or 'Untitled setting'}" ┐
│                                          [Switch setting ▾] [Edit frame] [Run ▸]│
├ Needs-you banner (if unreviewed drafts) ──────────────────────────────────────┤
├ Frame card ── readiness ring ─────────────────────────────────────────────────┤
│  pitch · tone · scale · central tension       │   ◐ 6/7 ready · "1 blocker"    │
├ Pillar progress grid (2×3) ───────────────────────────────────────────────────┤
│  one tile per pillar: count · "{n} new" · mini build-checklist % · → link      │
├ Readiness checklist (§8) ─────────────────────────────────────────────────────┤
│  7 rows, each ✓/✗ with the live reason + a "fix it" deep link                  │
├ Wiring health (§7) ───────────────────────────────────────────────────────────┤
│  orphan count · faction-clock count · "one thread" status                      │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Setting frame (§0)

Stored as a `type: campaign` doc in `03-Campaigns/` (today empty). Fields:

| Field | UI | Notes |
|-------|----|-------|
| `pitch` | one-line text input | "Frontier town bought out by a death cult that pays in gold" |
| `tone_primary` / `tone_secondary` | two `BadgeSelect` | grim / heroic / intrigue / survival… |
| `scale` | `BadgeSelect` | valley · city · region · continent |
| `central_tension` | textarea | "what is wrong in this world right now" |
| `player_buyin` | textarea | what characters the setting invites |
| `active` | toggle | the currently-selected setting |

**Edit frame** opens these as an inline panel (not a separate route). Saved via
**NEW** `POST /api/gm/campaign` → writes/updates the `03-Campaigns/*.md`. A
setting with no frame shows placeholder prompts ("Say it in one line…").

**Switch setting ▾** lists every `03-Campaigns` doc; supports **+ New setting**.
(Delivers the README roadmap item "multi-campaign workspace switching.")

## 4. Pillar progress grid

Six tiles (reuse the existing PILLARS array from `/gm/page.tsx`). Per tile:

- pillar icon + label (World & Places, Characters & NPCs, …)
- big count of entities in that pillar (draft + canon, canon-wins merge)
- `{n} new` warning chip when unreviewed drafts exist
- a thin **build-checklist progress bar** — % of that pillar's "build first"
  items satisfied (see §6 readiness rules)
- click → the pillar page (`/gm/places`, `/gm/npcs`, …)

This replaces today's hub item-preview lists; previews move into the pillar
pages where they belong.

## 5. Readiness checklist (§8) — the heart of the page

Seven rows from the guide, each computed live. Tag **NEW**
`GET /api/gm/readiness` returns `{ checks: [{ id, ok, detail, fixHref }] }`.

| # | Check | Pass condition (computed) | Fix link |
|---|-------|---------------------------|----------|
| 1 | Opening scene described | ≥1 `location` or `event` with a non-empty body | `/gm/places` |
| 2 | One detailed place | ≥1 `location`/`city`/`village`/`dungeon` canon **or** quality ≥7 | `/gm/places` |
| 3 | 3+ NPCs with wants | ≥3 `npc`/`character` whose body contains a "want/motivation" section | `/gm/npcs` |
| 4 | A faction making things worse | ≥1 `faction`/`organization` with a goal + clock | `/gm/factions` |
| 5 | A clock exists | ≥1 entity tagged/sectioned with a deadline/clock | `/gm/quests` |
| 6 | One hook + two threads | ≥1 `quest` flagged hook + ≥2 other `quest` | `/gm/quests` |
| 7 | World moves without players | ≥1 `timeline`/`event` or any faction clock | `/gm/factions` |

Each row: green ✓ / amber ✗ + the live `detail` ("2/3 NPCs — add 1 more") and a
**Fix it →** button to the relevant pillar page (pre-filtered). When all 7 pass,
the readiness ring goes solid green and **Run ▸** becomes primary/enabled.

> Heuristics (which body section counts as a "want", a "clock") live in the
> readiness endpoint, not the UI — keep them server-side and tunable.

## 6. Wiring health (§7)

- **Orphans:** count of entities with `relationships: []`. Click → a filtered
  list (the "No orphans" vault rule). Inline "Auto-link with Wiki agent" runs
  the `wikilink` agent over the selection.
- **Faction clocks:** how many factions have a defined "advance when ignored".
- **One thread:** is there ≥1 entity that links across ≥3 pillars (the guide's
  "one thread the party can pull")? Show the candidate thread if found.

## 7. Buttons & actions

| Control | Location | Action |
|---------|----------|--------|
| `Switch setting ▾` | header | pick/create `03-Campaigns` setting |
| `Edit frame` | header | toggle inline frame editor |
| `Run ▸` | header | enabled only when readiness = 7/7; opens a printable "session-zero" summary (frame + opening scene + key NPCs/factions/clocks) |
| `Fix it →` | each readiness row | deep-link to the responsible pillar page |
| `Auto-link` | wiring panel | dispatch `wikilink` agent on orphans |
| pillar tile | grid | navigate to pillar page |
| `Review {n} →` | needs-you banner | `/gm/review` |

## 8. States

- **No setting yet:** frame card is a single "Start your setting" CTA capturing
  the pitch; pillars/readiness render greyed with "0/7 ready".
- **Loading:** skeleton ring + skeleton tiles.
- **All ready:** confetti-free, just a solid green ring + enabled **Run ▸** and a
  one-line "This setting is ready to run."

## 9. Reuses / new work

- **Reuses:** PILLARS config, `readReviewItems`/`readLibraryItems`, `PageHeader`,
  `AutoRefresh`, the needs-you banner from today's `/gm`.
- **NEW:** `GET /api/gm/readiness`, `POST /api/gm/campaign`, `03-Campaigns`
  `type: campaign` frontmatter, the **Run ▸** session-zero summary view.
