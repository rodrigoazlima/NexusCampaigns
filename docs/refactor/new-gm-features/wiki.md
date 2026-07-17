# Knowledge Wiki - Page Spec

**Route:** `/gm/wiki` (index) · `/gm/wiki/{id}` (entity read view)
**Icon:** `BookOpen` · **Nav:** GAME MASTER → Wiki
**Agents:** `wiki` (synthesizes pages), `wikilink` (inserts `[[links]]`)

The read-and-connect surface across **every** pillar. Where the collection
pages are for *building* one domain, the Wiki is for *navigating the whole
graph*: search anything, open a clean read view, follow `[[wikilinks]]`, see
backlinks, and visualize the relationship web. It is the canon-facing twin of
`02-Library`.

---

## 1. Concept

Three things the pillar pages don't give you:
1. **One search across all types** - "find anything by name, tag, or text".
2. **A reading view** - canon rendered as a wiki page with working links and
   backlinks, not an editor.
3. **The graph** - the §7 "relationship web" made visible and walkable.

## 2. Routes & layout

### `/gm/wiki` - index

```
┌ PageHeader: BookOpen · "Knowledge Wiki" · "{N} entities · {E} links · {O} orphans" ┐
│                                                       [⚲ search-everything] [Graph]│
├ Left rail: type facets ─────────┬ Main: results ────────────────────────────────┤
│  ▸ Cast (n)                     │  result rows: token · id · type · excerpt · 🔗n │
│  ▸ Places (n)                   │  grouped by pillar, or flat when searching      │
│  ▸ Powers (n)  …                │                                                 │
│  ▢ Orphans (n)  ▢ Drafts (n)    │                                                 │
└─────────────────────────────────┴─────────────────────────────────────────────────┘
```

### `/gm/wiki/{id}` - entity read view

```
┌ Breadcrumb: Wiki / {pillar} / {id}        [Edit →] [Graph ◎] [Promote] (if draft)│
├ Hero: token/image (if any) · type badge · quality · tags ────────────────────────┤
├ Rendered markdown body (GFM, wikilinks clickable) ───────────────────────────────┤
├ Relationships ── outgoing [[links]] as chips ────────────────────────────────────┤
├ Backlinks ── "Linked from" - every entity that [[links]] here ───────────────────┤
└───────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Search (the primary control)

- Single search box, matches `id` + `tags` + body text + type.
- Results stream as you type; `Enter` jumps to the top hit.
- Scope chips: **All · Canon · Drafts**. Default All; Canon-only mirrors
  `02-Library`.
- Powered by **NEW** `GET /api/gm/graph` (or a `search` query) reading
  `readLibraryItems()` + `readReviewItems()`.

## 4. Lists / facets / filters

- **Left rail facets:** the six pillars (counts), plus **Orphans** (no
  relationships), **Drafts** (origin=draft), **Untagged**. Multi-select.
- **Result row:** token/type-chip · `id` (mono) · type badge · origin badge ·
  one-line excerpt · **link count** (🔗 n; `0` = orphan, amber).
- Sort: Relevance (when searching) · Name · Most-linked · Updated.
- Table toggle available (same columns as the collection archetype, read-only).

## 5. Graph view (`[Graph]`)

The §7 relationship web. **NEW** `GET /api/gm/graph` returns
`{ nodes: [{id,type,origin}], edges: [{from,to}] }` parsed from each file's
`relationships` / `[[wikilinks]]`.

- Force-directed graph; node color = pillar, size = degree.
- Click a node → opens its read view; hover → highlights its neighbors.
- Filter the graph by pillar facet and by canon/draft.
- **Orphan ring:** unconnected nodes parked at the edge - the visual form of the
  "no orphans" rule. Selecting one offers **Auto-link (Wiki agent)**.
- **Triangle finder:** highlights 3-node cycles (the guide's "triangles, not
  lists") - clusters that generate scenes.

## 6. Backlinks & link health

- Read view's **Backlinks** panel lists every entity whose `relationships`
  contain this id - computed by scanning all files (cheap; the vault is small).
- **Broken link** detector: a `[[slug]]` whose target file doesn't exist renders
  red with a **Create it** action (→ `POST /api/gm/create` pre-named) - turns a
  dangling link into a draft, the way wikilinks should seed new entities.

## 7. Buttons & actions

| Control | Where | Action |
|---------|-------|--------|
| `⚲ search` | index header | filter everything |
| `Graph` | index header | toggle graph view |
| pillar/orphan facet | left rail | filter results/graph |
| result row | results | → `/gm/wiki/{id}` |
| `Edit →` | read view | → `/gm/view/{id}` (drafts) |
| `Promote` | read view | `POST /api/gm/approve` (drafts) |
| relationship chip | read view | navigate to linked entity |
| backlink row | read view | navigate to linker |
| `Create it` | broken link | `POST /api/gm/create` for the missing slug |
| `Auto-link` | orphan/graph | dispatch `wikilink` agent on selection |
| `Re-synthesize` | read view | dispatch `wiki` agent to rebuild the page body |

The Wiki is **read + navigate + link**; it never edits bodies inline - that's
the `/gm/view/{id}` editor's job. The two AI actions (`wiki` re-synthesize,
`wikilink` auto-link) write only to `01-Processing` / `02-Library` `## Related`
sections, per the agents' existing contracts.

## 8. States

- **Empty vault:** "Nothing in the Library yet - build entities in the pillar
  pages, then promote them here."
- **No search results:** "No match - try a tag or a different term."
- **Entity not found (`/gm/wiki/{id}`):** 404 with "Open in editor" if it exists
  as a draft.
- **Graph with one node:** prompt to add relationships.

## 9. Reuses / new work

- **Reuses:** `readLibraryItems`, `readReviewItems`, the markdown preview from
  `ItemDetailView`, type-color map, `PageHeader`.
- **NEW:** `GET /api/gm/graph` (nodes+edges+backlinks), the read view route
  `/gm/wiki/{id}`, the force-directed graph component, broken-link detection.
- Existing roadmap tie-in: "Relationship map auto-rendering in `04-Relationships/`"
  - the graph view is its interactive front end.
