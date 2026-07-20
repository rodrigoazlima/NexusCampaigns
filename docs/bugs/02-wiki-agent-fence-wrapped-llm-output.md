# Bug: wiki-agent writes generic `lore-doc-*` stubs when the LLM wraps its reply in a code fence

**Status:** Open, not fixed (parked - investigating vision-agent sandbox bug first, see `01-vision-sandbox-wsl-hyperv-firewall.md`).
**Reported by:** dashboard Home page (`/home`) - Treasures & Lore row showed 4 (now 5) near-identical cards all labeled `lore-doc-<timestamp>-<hash>` instead of the actual generated items.

## Symptom

Every document dropped in `00-Inbox/docs/` produces a draft in `01-Processing/` with generic frontmatter instead of the LLM's actual structured output:

```yaml
---
status: draft
reviewed: false
quality: 0
created: '2026-07-20'
updated: '2026-07-20'
source:
- .knowledge-base/00-Inbox/docs/DOC_1784480391556_f1ae6e91.md
type: lore
id: lore-doc-1784480391556-f1ae6e91
uuid: 5d9e1ba0-ffb7-4ff9-8d94-c9c02e9f07b9
relationships: []
tags: []
suggestedQuality: 6
---
```

...with the **real** generated entity - correct `id`, `type`, `tags`, body sections - buried unparsed inside the note body as a fenced code block:

```
```yaml
---
id: artifact-sunken-bell-of-annun
type: artifact
status: draft
quality: 0
created: 2026-07-20
updated: 2026-07-20
tags: [artifact, lore, harbor, mystery, warning, fog]
source: []
reviewed: false
relationships: []
---

## Description
The Sunken Bell of Annun is a bronze bell that once rang from the harbor watchtower...
```
```

Two of the affected files (`artifact-sunken-bell-of-annun.md` and `artifact-sunken-bell-of-annun-20260720.md`) even carry byte-identical body content from two different source docs - the same generated note, stamped with two different generic `lore-doc-*` outer identities. On the dashboard (`pillars.ts`: `type: "lore"` → Lore pillar row), every one of these renders as a visually indistinguishable `lore-doc-*` card, reading as duplicates of the same item.

Confirmed via `system/state/inbox-queue.json`: these entries show `"wiki": "done"`, `"lore": "skip"` - this is the **wiki-agent** (`agents/wiki/tools/compile_wiki.py`), not the lore-agent, despite the `type: lore` frontmatter value (a coincidental name collision - `lore` here is one of the allowed entity *types*, not the lore-agent).

## Root cause

`agents/wiki/tools/compile_wiki.py`, `_enforce_and_write()` (line ~156-214):

```python
_FENCE_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
...
def _enforce_and_write(llm_output, source_name, out_path, fio):
    ...
    m = _FENCE_RE.match(llm_output)
    if m:
        fm = yaml.safe_load(m.group(1)) or {}
        body = llm_output[m.end():]
    else:
        fm   = {}
        body = llm_output
```

`_FENCE_RE` only matches if `llm_output` starts **literally** with `---` (anchored at string position 0). When the LLM wraps its entire reply in a Markdown code fence (`` ```yaml\n---\n...\n---\n...\n``` ``) - which it evidently does at least sometimes, per the 5 affected files - the string starts with `` ```yaml `` instead of `---`, the regex fails to match, and the code falls back to `fm = {}` / `body = llm_output` (the **entire** fenced blob, unparsed, becomes the note body).

The enforcement step then fills in defaults from an empty `fm`:
- `fm.get("type", "")` is `""`, not in `_ALLOWED_TYPES` → forced to `"lore"` (line 197-198).
- `fm.get("id")` is falsy → `f"{fm['type']}-{to_slug(Path(source_name).stem)}"` → `lore-doc-<slugified source filename>` (line 201-202).

This is why every affected draft looks the same: same fallback `type`, same `id` naming pattern, differing only by the source filename's timestamp/hash suffix - which reads as "duplicates" even when the underlying generated content differs.

Note the slug-extraction step just above (line 340-343) *does* work correctly even on fenced output - it regex-searches for `^id:\s*(.+)$` anywhere in the raw LLM text (not anchored to start), so it correctly finds `id: artifact-sunken-bell-of-annun` inside the fence for computing the **output filename** (`_unique_output`). Only the *frontmatter parse* in `_enforce_and_write` is anchored and fails - which is why the filenames (`artifact-sunken-bell-of-annun.md`) look right while the frontmatter inside is wrong.

## Suggested fix (not applied)

Strip a wrapping code fence before the frontmatter match, in `_enforce_and_write`:

```python
def _enforce_and_write(llm_output, source_name, out_path, fio):
    today = date.today().isoformat()

    stripped = llm_output.strip()
    fence_wrap = re.match(r"^```[\w-]*\r?\n(.*?)\r?\n```\s*$", stripped, re.DOTALL)
    if fence_wrap:
        stripped = fence_wrap.group(1)

    m = _FENCE_RE.match(stripped)
    if m:
        ...
        body = stripped[m.end():]
    else:
        fm   = {}
        body = stripped
    ...
```

Single call site (`_enforce_and_write` is only invoked from `main()`), so this is a one-function fix - no other caller needs touching.

## Cleanup still needed once fixed

The 5 existing malformed stubs in `01-Processing/` (`doc-1784505736617-69af4e9c.md`, `doc-1784546437261-969967b0.md`, `artifact-sunken-bell-of-annun.md`, `artifact-sunken-bell-of-annun-20260720.md`, `item-sunken-bell-of-annun.md`) are drafts, not yet human-reviewed/approved, so per AGENTS.md hard rules a human (not an agent, not this test suite) should either re-run wiki-agent against the original `00-Inbox/docs/*.md` sources after the fix lands, or manually re-flatten the fenced content into real frontmatter before archiving/deleting the stubs.

## Related

- `agents/wiki/CLAUDE.md` - wiki-agent contract; confirms `_enforce_and_write` is the sole place post-LLM enforcement happens.
- `system/dashboard/src/lib/pillars.ts` - `type: "lore"` → `Treasures & Lore` pillar, where all 5 stubs surface identically on Home.
- `system/dashboard/src/app/home/page.tsx`, `src/components/home/CarouselRow.tsx` - dashboard side is working as designed; it's rendering exactly what's in the frontmatter, which is the bug.
