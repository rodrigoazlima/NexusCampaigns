# GM Editor UI Guidelines

**Scope:** Interactive editor surfaces in the Game Master area
(`/gm/view/[id]`, `/gm/view/[id]/token`, and future editors).
**Audience:** Any agent building or modifying GM editor UI.
**Goal:** Keep editors consistent — canvas-first, mouse-driven, low-chrome,
every control self-documenting via tooltip.

Reference implementations:
- `src/components/gm/TokenEditorCanvas.tsx` — token editor
- `src/components/gm/ItemDetailView.tsx` — item detail
- `src/components/gm/Tip.tsx` — shared tooltip

---

## 1. Principles

1. **The subject is the UI.** The image/token/canvas is the hero. Chrome
   (panels, labels, sidebars) shrinks to the edges or disappears until hovered.
2. **Direct manipulation first.** Drag to move, scroll to zoom, click a thumbnail
   to switch. Sliders and number fields are the fallback, not the primary path.
3. **Smart small buttons.** Prefer a 32×32 icon button with a tooltip over a
   wide labeled button. Reserve labels for the single primary action of a view
   (e.g. `Promote`, `Save`).
4. **Every control explains itself.** Icon-only controls MUST have a `<Tip>`.
   Include the keyboard shortcut in the tooltip when one exists.
5. **Feedback is transient, not sticky.** Status → auto-dismissing toast (~3 s).
   Live values (zoom %) → overlay that fades after the gesture.
6. **Integrate related media.** When two assets belong together (source image +
   its token), show them in one frame with the smaller composited onto the
   larger, not in separate panels. The companion is clickable and routes to its
   editor.

---

## 2. Color tokens

Use Tailwind theme tokens — never raw hex in components.

| Token | Use |
|-------|-----|
| `surface` `surface-1..4` | Backgrounds, ascending elevation |
| `primary` (#0C5CAB) | Selected / focus / links / token affordance |
| `success` | Save, promote, confirm |
| `danger` | Reject, destructive |
| `warning` | Flag, caution |
| `zinc-*` | Text + neutral borders |

Variant convention for bordered controls: `border-<token>/40 bg-<token>/10
text-<token> hover:bg-<token>/20`.

---

## 3. Reusable components

### `<Tip>` — tooltip (`src/components/gm/Tip.tsx`)

Wrap any control. Hover-only, no JS state, `group/tip` driven.

```tsx
<Tip label="Zoom out" side="bottom" shortcut="−">
  <button>…</button>
</Tip>
```

- `side`: `top | bottom | left | right` (default `top`). Use `bottom` for
  top-bar controls, `left` for controls on a right edge.
- `shortcut`: optional — renders a `<kbd>` chip after the label.

### Icon button

Both editors define a local icon button (`IconBtn` / `ActionBtn`) — a 32×32
(`w-8 h-8`) rounded-lg bordered button wrapped in `<Tip>`, with color variants
and a `busy` spinner state. Pattern:

```tsx
<ActionBtn label="Reject (quality → 1)" variant="danger" onClick={…} busy={loading}>
  <XCircle size={14} />
</ActionBtn>
```

Variants: `ghost` (default), `primary`, `success`, `danger`, `warning`,
`star`. If you build a third editor, lift the shared parts rather than copying
a third time.

### `<BadgeSelect>` — inline editable badge (`ItemDetailView.tsx`)

A native `<select>` styled as a colored badge with a `ChevronDown`. Use for
enum metadata edited in place (type, status) instead of a labeled dropdown in a
form panel.

---

## 4. Layout patterns

### Top bar

`h-10`, `bg-surface-1`, `border-b border-surface-3`, `z-20`, flex row:

```
← back  /  <id/breadcrumb>  [inline badges]   …spacer…   [status]  [primary action]
```

Keep it one line. Push the primary action to the right. Make it sticky on
scrollable views.

### Floating control strip

For canvas editors, group transform controls in a single pill floating above the
canvas — not in a side panel:

`bg-zinc-900/70 border border-zinc-800/80 backdrop-blur-sm rounded-xl px-2.5 py-1.5 shadow-xl`

Separate logical groups with a thin vertical divider (`w-px h-4 bg-zinc-700/60`).

### Thumbnail strip

Horizontal, scrollable, circular thumbs. Selected: `border-zinc-400 scale-110`.
Unselected: `opacity-50 hover:opacity-80`. Mark a special item (e.g. default
frame) with a small corner dot.

### Integrated media + companion

Source image fills a hero frame; the token sits as a `rounded-full` circle in a
corner with a ring + shadow. Hover reveals a pencil overlay; click routes to the
companion's editor. The hero itself is `cursor-zoom-in` → opens the modal.

### Hover-revealed controls

Secondary controls on a hero (enlarge, replace) live in an
`opacity-0 group-hover:opacity-100` toolbar. Primary affordances (the token
companion) stay visible.

---

## 5. Feedback

| Need | Pattern |
|------|---------|
| Action result | Toast: fixed, bottom-center, pill, icon + text, auto-dismiss ~3 s. `success`/`danger` token colors. |
| Live transform value | Centered overlay on the canvas, fades ~1.4 s after the gesture (see `flashZoom`). |
| In-flight | Swap the control's icon for `<Loader2 className="animate-spin" />` (size 14) or a CSS spinner; disable the control. |
| Disabled | `opacity-30 cursor-not-allowed`; keep the tooltip working. |

One toast at a time — replace, don't stack. Clear its timer on each new message.

---

## 6. Interaction

- **Mouse:** drag = move, wheel = zoom (`e.preventDefault()`), click thumb =
  select, click hero = enlarge.
- **Touch:** mirror single-finger drag; set `touchAction: 'none'`.
- **Keyboard (canvas editors):** arrows nudge, `+`/`-`/`0` zoom, `R` reset,
  `[`/`]` cycle, `S` save, `Esc` back. Guard against typing in inputs
  (`if (e.target instanceof HTMLInputElement) return`). Surface each binding in
  the relevant tooltip.
- **Inline edit:** click-to-edit (id rename) over always-visible form fields.
  `Enter` confirms, `Esc` cancels, with explicit ✓/✗ buttons.

---

## 7. Persistence

- Auto-save after a settle delay (~1.5 s debounce) on canvas edits; keep an
  explicit Save for save-and-return.
- Cache-bust refreshed images with `?t=${Date.now()}` so the new asset shows.

---

## 8. Do / Don't

**Do**
- Maximize the subject; minimize chrome.
- Tooltip every icon-only control; add its shortcut.
- Use theme tokens and the variant convention.
- Reuse `<Tip>`; lift shared button logic when a pattern hits a third file.

**Don't**
- Ship icon-only buttons without tooltips.
- Stack permanent status text where a toast belongs.
- Rebuild a side-panel form when inline editing fits.
- Hardcode hex colors or pixel sidebars into an editor view.
- Trigger native `alert`/`confirm` in new flows — prefer inline confirm
  (existing `confirm()` calls are legacy; don't add more).
