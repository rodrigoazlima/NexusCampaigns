# Impl: Session Builder Agent

**Phase:** P4  
**Priority:** Low  
**Effort:** 3 days  
**Depends on:** Adventure Builder (P4), session note format convention

---

## Problem

Adventure modules (from the Adventure Builder) describe the full arc but do not produce session-by-session prep. The DM still needs to translate "Act 2: Complication" into a concrete 3-hour session with opening scene, middle beats, and a satisfying stopping point. This is mechanical work the agent can assist with — especially when prior session notes are available to track where the party actually is.

---

## Goal

The Session Builder reads the adventure module for an arc plus any existing session notes, and produces a session prep document for the NEXT unplayed session. Output goes to `03-Campaigns/{arc}/sessions/session-{N:02d}-prep.md`.

The session prep includes: opening scene, NPC reminders (stats/motivations), location description, 3-5 encounter seeds, key decisions the party may face, and a suggested stopping point.

---

## Trigger

Session Builder runs on demand, not on a fixed schedule. It is triggered when:
1. A `request-session-{N}.yaml` file exists in `03-Campaigns/{arc}/` (human drops a trigger file), OR
2. A signal `adventure-module-ready` is emitted by the Adventure Builder

It does NOT run automatically without human intent. The DM decides when to prep a session.

---

## Inputs

1. **Adventure module:** `03-Campaigns/{arc}/adventure-module.md` (or approved version)
2. **Prior session notes:** `03-Campaigns/{arc}/sessions/session-*.md` — played sessions
3. **Session request file:** `03-Campaigns/{arc}/request-session-{N}.yaml` — optional parameters
4. **Canon entities:** `02-Library/` — for NPC stat lookups

---

## Session Request File Format

Human creates `03-Campaigns/A1-Annun/request-session-03.yaml`:

```yaml
session: 3
arc: A1-Annun
duration_hours: 3
focus: combat          # combat | roleplay | exploration | mixed
party_state: |
  Party is level 4. Lost one party member last session (unconscious, stable).
  They are in the cursed forest, night is falling.
  Tomas the ranger has a personal hook with npc-elder-annun (unresolved).
notes: |
  Players seem engaged with the faction conflict. Less interested in dungeon crawl.
  Introduce the blacksmith's secret this session if natural.
```

All fields optional except `session` and `arc`. Agent uses defaults for missing fields.

---

## Output Format

`03-Campaigns/A1-Annun/sessions/session-03-prep.md`:

```markdown
---
arc: A1-Annun
session: 3
generated: 2026-06-10
status: draft
reviewed: false
---

# Session 3 Prep — The Fall of Annûn

## Opening Scene
[Specific paragraph describing where the session starts — continue from last session's stopping point]

## Session Goals
1. Advance hook: [merchant disappearance from seed]
2. Resolve: [personal hook from request file]
3. Optional: [introduce blacksmith secret if pacing allows]

## Key NPCs This Session
### [[npc-elder-annun]]
- Role: exposition source, possible ally
- Current state: [from prior session notes]
- Motivation: [from Library entity]
- If party is hostile: [contingency]

### [[npc-blacksmith-cirit]]
- Role: secret holder
- Reveal condition: [if party investigates merchant hook]

## Location: [[location-cursed-forest]]
[2-paragraph DM description — atmosphere, notable features, hazards]

## Encounter Seeds

### 1. [Encounter name]
**Type:** Combat / Roleplay / Environmental
**Participants:** [[creature-shadow-wolf]] × 3
**Stakes:** Party must reach village before dawn
**Scaling:** If overwhelmed, reinforcements arrive as allies

### 2. [Encounter name]
...

## Key Decisions
- Will party investigate the abandoned campsite? → leads to merchant subplot
- Will party confront the guard patrol? → triggers faction conflict Act 3

## Suggested Stopping Point
[Describe a dramatically satisfying break point]

## DM Notes
[Tone reminders, player hook callbacks, things to improvise around]
```

---

## Scope

Files to create:
- `agents/session-builder/agent.json`
- `agents/session-builder/tools/__init__.py`
- `agents/session-builder/tools/session_builder_agent.py`
- `agents/session-builder/prompts/system.md`
- `agents/tests/test_session_builder.py`

Files to modify:
- `agents/session-builder/AGENT.md` — fill stub

---

## `agent.json`

```json
{
  "tasks": {
    "session-builder-agent": {
      "intervalSeconds": 3600,
      "description": "Generate session prep from adventure module + prior sessions when request file present",
      "signal_triggers": ["adventure-module-ready"],
      "dispatch": {
        "type": "claude-api",
        "claude_api": {
          "model": "claude-sonnet-4-6",
          "system_file": "prompts/system.md",
          "tools_module": "session-builder.tools.session_builder_agent",
          "history_file": "session-builder-history.json",
          "max_tokens": 6144,
          "timeout_seconds": 600,
          "max_tool_rounds": 30
        }
      }
    }
  }
}
```

Runs hourly but only does work when a `request-session-N.yaml` exists. Effectively on-demand.

---

## Tools

### `list_pending_session_requests() → list[SessionRequest]`

Scans `03-Campaigns/*/request-session-*.yaml`. Returns requests where `sessions/session-{N}-prep.md` does NOT already exist (i.e., not already generated).

```python
@dataclass
class SessionRequest:
    arc: str
    session_number: int
    request_path: Path
    params: dict
    adventure_module_path: Optional[Path]  # None if not found
    prior_sessions: list[Path]             # sorted session notes
```

### `read_adventure_module(arc: str) → str`

Reads `03-Campaigns/{arc}/adventure-module.md` (or `approved-module.md` if exists). Returns full content.

### `read_prior_sessions(arc: str) → list[SessionNote]`

Reads all `sessions/session-*.md` files for arc. Returns parsed:

```python
@dataclass
class SessionNote:
    session_number: int
    path: Path
    body: str
    stopping_point: str   # extracted from ## Stopping Point section if present
```

### `read_entity(slug: str) → EntityContent`

Same as in Adventure Builder — reads from `02-Library/`. Used for NPC stat lookup.

### `write_session_prep(arc: str, session: int, content: str) → None`

Writes `03-Campaigns/{arc}/sessions/session-{N:02d}-prep.md`. Always `status: draft`. Never overwrites a file that already has `status: approved` (human-approved session notes are preserved).

After write: deletes the `request-session-{N}.yaml` trigger file (consumed).

### `write_log(sessions_generated: int, skipped: int, failed: int) → None`

Standard log format.

---

## System Prompt (`agents/session-builder/prompts/system.md`)

```markdown
# Session Builder Agent

You are the Session Builder for a Dungeon Master knowledge vault.
Your role: generate specific, actionable session prep documents from adventure modules and prior session notes.

## Workflow

1. Call `list_pending_session_requests` — find arcs needing session prep
2. For each request:
   a. Call `read_adventure_module` for the arc
   b. Call `read_prior_sessions` for played sessions (understand current party state)
   c. Call `read_entity` for key NPCs appearing in this session
   d. Generate session prep document — specific, not generic
   e. Call `write_session_prep`
3. Call `write_log`

## Rules

- Base session on `party_state` from request file — do not start from scratch
- Never repeat encounters or scenes from prior session notes
- Use entity stats from 02-Library/ — do not invent stats
- Session length implied by `duration_hours` (3h = 3-4 encounters max)
- Match tone from adventure module, adjust per request file `focus` field
- Prep is a draft (status: draft, reviewed: false) — human DM adjusts before use
- After writing, the request file is consumed (deleted)
- If adventure module is absent: skip request, log warning
```

---

## Signal: Adventure Module Ready

Adventure Builder emits after writing a module:

```python
emitter.emit(
    signal_type="adventure-module-ready",
    emitter="adventure-builder-agent",
    ref=arc,
)
```

Session Builder receives via `signal_triggers: ["adventure-module-ready"]`. This means: if the DM has a `request-session-1.yaml` for a new arc and the Adventure Builder just finished the module, Session Builder runs immediately.

---

## Tests

`agents/tests/test_session_builder.py`:

```python
def test_skips_arc_without_adventure_module(tmp_path):
    # request-session-1.yaml exists, no adventure-module.md
    # Assert: request returned with adventure_module_path=None
    # Assert: no prep written

def test_consumes_request_file_after_write(tmp_path):
    # Write session prep
    # Assert: request-session-N.yaml deleted

def test_never_overwrites_approved_prep(tmp_path):
    # Existing session-03-prep.md with status: approved
    # Assert: write_session_prep skips

def test_prior_sessions_parsed_correctly(tmp_path):
    # 2 prior session notes in sessions/
    # Assert: list ordered by session number
    # Assert: stopping_point extracted from ## Stopping Point section

def test_no_sessions_yet_handled(tmp_path):
    # No sessions/ dir exists
    # Assert: prior_sessions returns empty list, no error
```

---

## Success Criteria

- Session prep generated whenever `request-session-N.yaml` exists and adventure module is present.
- Request file consumed (deleted) after prep is written.
- Prior session content is never repeated in new prep.
- NPC stats come from `02-Library/` — no invented stats.
- Output matches session prep format with all required sections.
- Approved session notes never overwritten.
- Agent handles missing adventure module gracefully (skip + log).
