# Default "No Image Yet" Icons

Fallback UI icon prompt for every entity/image category - shown in the
dashboard when an item has no image attached. One file per category.

Not full art. A single blank/unmarked medieval object per category (empty
picture frame, blank shield, unlit candle, unopened scroll...) - the object
itself is the deliberately-empty version of its category's usual symbol, so
the icon reads as "nothing here yet" without any text. Meaning: *no image
selected for this item yet - drop one in if you want, or keep this as the
default.*

`ponytail:` doc only - no worker consumes this yet. Wire in when the
dashboard needs a real default-icon asset; until then, copy a file's
contents into whatever image model is on hand.

## Categories

18 allowed `type:` values (`AGENTS.md` → Entity Types), grouped by dashboard
pillar (`system/dashboard/src/lib/pillars.ts`), plus `battlemap` and `scene`
- first-class naming-convention categories (`AGENTS.md` → Naming Rules) that
describe images, not entities.

| Pillar | Files | Blank object |
|---|---|---|
| World & Places | [location.txt](location.txt) | stone waymarker, no inscription |
| | [city.txt](city.txt) | empty gate arch |
| | [village.txt](village.txt) | cottage, unlit chimney |
| | [dungeon.txt](dungeon.txt) | closed iron-barred door |
| Characters & NPCs | [npc.txt](npc.txt) | open portrait locket, empty |
| | [character.txt](character.txt) | blank heraldic shield |
| Factions & Powers | [faction.txt](faction.txt) | unmarked banner |
| | [organization.txt](organization.txt) | unstamped wax seal |
| | [religion.txt](religion.txt) | unlit candle |
| Quests & Story | [quest.txt](quest.txt) | unopened scroll |
| | [event.txt](event.txt) | empty hourglass |
| | [timeline.txt](timeline.txt) | blank sundial |
| Bestiary | [creature.txt](creature.txt) | clawed footprint, no creature |
| | [monster.txt](monster.txt) | lone fang |
| | [encounter.txt](encounter.txt) | sheathed sword |
| Treasures & Lore | [item.txt](item.txt) | closed chest |
| | [artifact.txt](artifact.txt) | empty pedestal |
| | [lore.txt](lore.txt) | blank-cover book |
| Image-only | [battlemap.txt](battlemap.txt) | unmarked flagstone tile |
| | [scene.txt](scene.txt) | empty picture frame |

## Shared design rules (every file)

- One element only, centered, generous padding.
- Flat linework, single muted ink tone (charcoal/sepia) - no full-color
  painterly rendering. The desaturation itself signals "placeholder" next
  to real classified art.
- No shading gradients, no background scene, no text, no watermark.
- Aspect ratio: 1:1, legible at small (dashboard thumbnail) size.

Fully generic - no `{name}`/`{tags}` placeholders. One icon per category,
reused for every entity of that type until a real image is attached.

## Usage

1. Open the file matching the entity's `type:` (or `battlemap.txt`/
   `scene.txt` for image-only slots).
2. Generate as-is - no fields to fill.
3. This is a UI placeholder, not vault content: don't drop the result into
   `00-Inbox/images/`.
