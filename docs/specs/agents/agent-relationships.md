# Agent Directory & Path Relationships

Derived from each `agents/<name>/AGENT.md` (inputs/outputs/state_files/commit_scope/restrictions). Paths capped at depth 2. Excludes `agents/tests`.

Every agent below also links to `agents/shared` (shared runtime library) and `system/state` (own `system` link if already present covers this) — omitted from each row for brevity. Every agent also owns a real (non-linked) `prompts/`, `state/`, `tools/` dir.

| Agent | Related Paths |
|---|---|
| adventure-builder | agents/adventure-builder, knowledge-base/02-Library, knowledge-base/03-Campaigns, agents/lore, agents/canon, agents/relationship |
| canon | agents/canon, knowledge-base/02-Library |
| classification | agents/classification, knowledge-base/00-Inbox, knowledge-base/01-Processing, knowledge-base/02-Library |
| cleanup | agents/cleanup, agents/runtime, agents/review, agents/repair, agents/canon, agents/deduplication |
| curator | agents/curator, knowledge-base/01-Processing |
| deduplication | agents/deduplication, knowledge-base/00-Inbox, knowledge-base/01-Processing, knowledge-base/02-Library |
| encounter-builder | agents/encounter-builder, knowledge-base/02-Library, knowledge-base/03-Campaigns |
| ingestion | agents/ingestion, knowledge-base/00-Inbox, system/state |
| lore | agents/lore, knowledge-base/00-Inbox, knowledge-base/01-Processing, knowledge-base/02-Library, agents/vision, system/state |
| relationship | agents/relationship, knowledge-base/02-Library, knowledge-base/04-Relationships |
| repair | agents/repair, agents/runtime, agents/review, agents/vision, agents/* (agent.json of every agent), system/state, system |
| review | agents/review, agents/runtime, knowledge-base/01-Processing, agents/* (agent.json of every agent) |
| runtime | agents/runtime, agents/* (all agent folders), system (all subfolders) |
| search | agents/search, knowledge-base/01-Processing, knowledge-base/02-Library |
| session-builder | agents/session-builder, knowledge-base/03-Campaigns, agents/adventure-builder |
| token | agents/token, agents/vision, knowledge-base/00-Inbox, knowledge-base/05-Assets |
| vision | agents/vision, knowledge-base/00-Inbox, knowledge-base/01-Processing, system/state |
| wiki | agents/wiki, knowledge-base/01-Processing, knowledge-base/02-Library, system/state |
| wikilink | agents/wikilink, knowledge-base/02-Library |
