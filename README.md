<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->
<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]



<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/rodrigoazlima/NexusCampaigns">
    <img src="system/assets/icon/Primary App Icon.png" alt="Logo" width="400" height="400">
  </a>

  <h3 align="center">Nexus Campaigns</h3>

  <p align="center">
    AI-powered Dungeon Master vault that turns raw campaign inspiration into reusable, linked, quality-gated knowledge assets.
    <br />
    <a href="https://github.com/rodrigoazlima/NexusCampaigns"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/rodrigoazlima/NexusCampaigns">View Demo</a>
    &middot;
    <a href="https://github.com/rodrigoazlima/NexusCampaigns/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/rodrigoazlima/NexusCampaigns/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
        <li><a href="#system-architecture">System Architecture</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#quick-install-one-command">Quick Install (one command)</a></li>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#manual-installation">Manual Installation</a></li>
        <li><a href="#installing-at-a-custom-location">Installing at a Custom Location</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#dashboard">Dashboard</a></li>
        <li><a href="#agent-daemon">Agent Daemon</a></li>
        <li><a href="#monitoring">Monitoring</a></li>
      </ul>
    </li>
    <li>
      <a href="#reference">Reference</a>
      <ul>
        <li><a href="#folder-structure">Folder Structure</a></li>
        <li><a href="#pipeline-workflow">Pipeline Workflow</a></li>
        <li><a href="#agents">Agents</a></li>
        <li><a href="#configuration">Configuration</a></li>
        <li><a href="#metadata-standard">Metadata Standard</a></li>
        <li><a href="#naming-convention">Naming Convention</a></li>
        <li><a href="#wikilinks--linking-rules">Wikilinks &amp; Linking Rules</a></li>
        <li><a href="#logging">Logging</a></li>
        <li><a href="#security-constraints">Security Constraints</a></li>
      </ul>
    </li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

Nexus Campaigns is an AI-powered vault that transforms raw campaign inspiration — images, documents, and notes — into reusable, linked, quality-gated knowledge assets for Dungeon Masters.

A pipeline of scheduled agents ingests source material, classifies it with vision and language models, generates NPC sheets and circular tokens, enriches metadata, and weaves `[[wikilinks]]` between entities. A human reviews every draft and is the only one who can promote content to canon.

* **Vault root:** `.knowledge-base/`
* **Version:** 1.0 · **Date:** 2026-06-09

> Every agent reads `AGENTS.md` before making changes. It is the operating system of this vault.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



### Built With

* [![Next][Next.js]][Next-url]
* [![React][React.js]][React-url]
* [![TypeScript][TypeScript.com]][TypeScript-url]
* [![Tailwind][Tailwind.com]][Tailwind-url]
* [![Python][Python.com]][Python-url]
* [![Anthropic][Anthropic.com]][Anthropic-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>



### System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ nexus.runner (single process)                                        │
│                                                                      │
│  00-Inbox/ ──► ingestion worker ── registers entries ──┐             │
│                                                        ▼             │
│                     inbox-queue.json (slot: pending→done/skip/error) │
│                          │ pending slots = work items                │
│          ┌───────────────┼───────────────────┐                       │
│          ▼               ▼                   ▼                       │
│   [Vision Agent]   [Lore Agent]   queue workers: thumbnails ·        │
│   (LLM dispatch)   [Classification]  token · wikilink · shortfiles   │
│                    [Wiki Agent]                                      │
│          │                                                           │
│          ▼                                                           │
│  (human review — sets status: approved, quality: N)                  │
│          ▼                                                           │
│    02-Library/ (canon) ──► wikilink worker → [[links]]               │
│                                                                      │
│  scheduled workers (cron-like):                                      │
│    report (15 min) · cleanup (daily) · maintenance (daily + signal)  │
└──────────────────────────────────────────────────────────────────────┘
```

LLM agents dispatch via `agent.json` (subprocess); static workers run **in-process** — no per-task interpreter spawn, no agent scaffolding.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

### Quick Install (one command)

> **Requires Administrator.** Installs everything — Python dependencies, the agent pipeline service, and the dashboard (built and served on **port 48080**) — registers both to auto-start at boot, and starts them immediately.

```powershell
# 1. Clone the repo
git clone https://github.com/rodrigoazlima/NexusCampaigns.git
cd NexusCampaigns

# 2. From an ELEVATED PowerShell 7 (Run as Administrator), one command installs and starts it all:
pwsh -ExecutionPolicy Bypass -File system\ops\setup-service.ps1
```

When it finishes, the dashboard is live at **http://localhost:48080**.

| Manage | Command |
|--------|---------|
| Status | `pwsh -File system\ops\setup-service.ps1 -Status` |
| Uninstall | `pwsh -File system\ops\setup-service.ps1 -Uninstall` |
| Clean install | `pwsh -File system\ops\setup-service.ps1 -CleanInstall` |
| Options | `-NoDashboard` to skip dashboard · `-DashboardPort 9000` for custom port · `-RunPreFlight` to run agent test cycle first (~60s) |

Generates default settings at `system\.env.local` (`PROJECT_ROOT`, `VAULT_ROOT`, `PORT`, `HOSTNAME`) derived from `system\.shared\config\global.json` — change the port once in `global.json` (`ports.dashboard`). Previous installs are automatically removed before each fresh install.

Without Administrator the installer falls back to a per-user (at-logon) install via the HKCU Run key. NSSM + Admin is recommended for an always-on Windows service — `winget install NSSM.NSSM`.

### Prerequisites

* [PowerShell 7+](https://learn.microsoft.com/powershell/) (`pwsh`)
* [Python 3.11+](https://www.python.org/) — agent runtime
* [Node.js 18+](https://nodejs.org/) — dashboard
* [NSSM](https://nssm.cc/) (optional) — `winget install NSSM.NSSM`, for the always-on Windows service
* A locally-hosted LLM endpoint (e.g. `qwen3-vl-4b-instruct`) for vision/lore agents — no external API keys required

### Manual Installation

Prefer to run the pieces by hand instead of the one-command installer?

1. Clone the repo
   ```sh
   git clone https://github.com/rodrigoazlima/NexusCampaigns.git
   cd NexusCampaigns
   ```
2. Install dependencies
   ```powershell
   python -m pip install -r requirements.txt
   cd system\dashboard; npm install
   ```
3. Configure ports and the vault root. Ports live in the codebase config; the
   one-command installer reads them and generates `system\.env.local` (canonical)
   and copies it to `system\dashboard\.env.local` for Next.js. Re-run with `-Force` to regenerate.

   | Setting | Where | Default |
   |---------|-------|---------|
   | `ports.dashboard` | `system\.shared\config\global.json` | `48080` |
   | `ports.host` | `system\.shared\config\global.json` | `0.0.0.0` |
   | `VAULT_ROOT` | `system\.env.local` (or `NEXUS_VAULT_ROOT`) | `<repo>\.knowledge-base` |
4. Start the agent daemon and dashboard — see [Usage](#usage).

### Installing at a Custom Location

Cloning to a non-default path (e.g. an OneDrive-synced folder), or keeping the
vault in a separate repo/drive from the app repo? Pass `-ProjectRoot` and
`-VaultRoot` explicitly — both accept any path, on any drive:

```powershell
pwsh -ExecutionPolicy Bypass -File system\ops\setup-service.ps1 `
    -ProjectRoot "C:\path\to\NexusCampaigns" `
    -VaultRoot   "C:\path\to\vault-repo\.knowledge-base"
```

* `-ProjectRoot` defaults to the app repo root (two levels above `system\ops`)
  — only needed if the script is invoked from somewhere else, or wrapped by another script.
* `-VaultRoot` defaults to `<ProjectRoot>\.knowledge-base` — set it to point at a
  separately-cloned vault repo. The script creates the directory if missing and
  links `<ProjectRoot>\.knowledge-base` to it via an NTFS junction.
* If `-VaultRoot` already has its own `.git` (e.g. cloned from a separate vault
  repo), do **not** pass `-VaultGitInit` — that flag is only for turning a plain
  folder into a new git repo, and will error/misinit against an existing one.
* Splitting the vault into its own repo entirely? See
  [`docs/specs/guides/vault-repo-split-tutorial.md`](docs/specs/guides/vault-repo-split-tutorial.md).
* Elevation: the installer needs Administrator for the NSSM service install. If
  your account has UAC set to "Elevate without prompting"
  (`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\ConsentPromptBehaviorAdmin = 0`),
  `Start-Process pwsh -Verb RunAs` elevates silently — no password/dialog needed.
  Otherwise expect a UAC prompt.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

### Dashboard

The Quick Install already builds and serves the dashboard on port 48080. To run it manually in dev mode:

```powershell
cd system\dashboard
npm run dev
```

Binds `0.0.0.0:48080` — accessible on local LAN:
- Local: http://localhost:48080
- LAN: http://`<your-ip>`:48080

### Agent Daemon

Start:
```powershell
powershell -NonInteractive -File system\ops\daemon.ps1
```

Restart (kill existing first):
```powershell
Get-Process python | Where-Object { $_.CommandLine -like "*runner.py*" } | Stop-Process -Force
powershell -NonInteractive -WindowStyle Hidden -File system\ops\daemon.ps1
```

### Monitoring

```powershell
# Live log tail
Get-Content 'agents\runtime\state\logs\automation.log' -Tail 50 -Wait

# Status check
pwsh -File 'system\ops\setup-service.ps1' -Status

# Uninstall
pwsh -File 'system\ops\setup-service.ps1' -Uninstall

# Clean install — wipes all generated state, indexes, configs, and build artifacts
# Preserves 00-Inbox (source), 02-Library, 03-Campaigns, 05-Assets, 99-Archive
# Requires typing 'yes' to confirm
pwsh -File 'system\ops\setup-service.ps1' -CleanInstall
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- REFERENCE -->
## Reference

### Folder Structure

| Folder | Purpose | Rules |
|--------|---------|-------|
| `00-Inbox/` | Raw source material drop zone | Read-only by agents. May rename files (emoji cleanup) only. |
| `00-Inbox/images/` | Campaign art organized by arc (`A1`, `A2`, `A9 Desert`, etc.) | Agents rename to slug format; never delete. |
| `00-Inbox/docs/` | World-building documents, PDFs | Read-only; DOCX → GFM Markdown via pandoc. |
| `00-Inbox/songs/` | Ambient music references | Read-only. |
| `00-Inbox/tokens/` | Token frames / molduras | Read-only. |
| `01-Processing/` | AI-generated drafts pending human review | Agents write here. Single source of truth for unreviewed entities. |
| `02-Library/` | Approved canon knowledge | Human-only promotion. Agents must never write here. |
| `03-Campaigns/` | Campaign-specific material | References Library entities via `[[wikilink]]`. No duplicates. |
| `04-Relationships/` | Auto-generated knowledge graphs | Regenerated by relationship agents. Do not edit manually. |
| `05-Assets/` | Approved media (portraits, tokens, maps) | Every asset must link to ≥1 Library entity. |
| `99-Archive/` | Retired approved content | Never permanently delete. |

### Pipeline Workflow

```
00-Inbox  →  01-Processing  →  (human review)  →  02-Library
                                                        ↓
                                                   03-Campaigns
                                                   04-Relationships
                                                   05-Assets
```

1. Drop sources into `00-Inbox/` — treat as read-only
2. Automation agents process `00-Inbox/` → write drafts to `01-Processing/`
3. Human reviews drafts, sets `status: approved` + `quality: N`
4. Approved content promoted to `02-Library/` (or `03-Campaigns/`, `05-Assets/`)
5. Relationships auto-indexed into `04-Relationships/`

**Quality gate for `02-Library/`:** `status: approved` + `quality >= 7` + `reviewed: true`
No agent may write these fields as `true` / `approved`.

### Agents & Workers

**LLM agents** (per-agent folder, `agent.json` dispatch):

| Agent | Role |
|-------|------|
| Vision | Image classification via vision LLM; writes `01-Processing/` drafts |
| Lore | NPC sheet generation from image + scenario context |
| Classification | Tag enrichment and type inference for sparse notes |
| Wiki | Synthesizes entity pages from markdown notes |

**Static workers** (in-process `nexus.workers.*`, configured in `agents/registry.yaml` `workers:` block — queue workers poll every cycle, scheduled workers run on an interval):

| Worker | Kind | Role |
|--------|------|------|
| Ingestion | queue | Emoji cleanup, DOCX→MD conversion, queue registration |
| Thumbnails | queue | 320px webp thumbnails for the dashboard gallery |
| Token | queue | Circular token generation with moldura frame |
| Wikilink | queue | Inserts `[[wikilinks]]` into `## Related` sections of `02-Library/` |
| Shortfiles | queue | Flags drafts under 10 body lines for reprocessing |
| Report | scheduled | Pending review list, orphan detection, quality suggestions |
| Cleanup | scheduled | Purges logs/reports older than configured retention |
| Maintenance | scheduled + signal | Fixes stale locks, missing dirs, broken image refs; detects overdue agents; resets retryable `error` queue slots |

LLM calls run at `temperature: 0`, up to 3 retries with 3s backoff. Connection errors → skip batch, retry next run.

### Configuration

Tasks are defined in each agent's `agent.json`. The runtime discovers them automatically:

```json
{
  "tasks": {
    "agent-id": {
      "intervalSeconds": 3600,
      "description": "Agent description",
      "dispatch": {
        "type": "claude-api",
        "claude_api": {
          "model": "claude-haiku-4-5-20251001",
          "system_file": "prompts/system.md",
          "tools_module": "agent.tools.agent_name"
        }
      }
    }
  }
}
```

| Interval | Tasks |
|----------|-------|
| Short (e.g., 900s) | Review, Repair |
| Hourly | Ingestion, Vision, Lore, Token, Classification, Wiki, Wikilink |
| Daily | Cleanup |

### Metadata Standard

All `01-Processing/` and `02-Library/` entities use this frontmatter:

```yaml
---
id: {type}-{slug}
type: {entity-type}
status: draft | review | approved | archived
quality: 1-10
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags:
  - tag1
source:
  - filename.ext
sha256: {hex string}
reviewed: false
relationships:
  - "[[entity-slug]]"
---
```

**Allowed `type` values:**
`npc` · `character` · `faction` · `location` · `city` · `village` · `dungeon` · `item` · `artifact` · `quest` · `encounter` · `creature` · `monster` · `event` · `religion` · `organization` · `timeline` · `lore`

**Quality scores:**

| Score | Meaning |
|-------|---------|
| 1–3 | Low quality — reject |
| 4–6 | Needs review |
| 7–8 | Good |
| 9–10 | Library candidate |

### Naming Convention

Slug format: `{type}-{descriptors}.md`

```
npc-necromancer-black-hollow.md
quest-missing-villagers.md
location-black-hollow-cemetery.md
battlemap-dungeon-cirit-01.md
```

Forbidden: `final_v2`, `new`, `cool`, `Untitled`, uppercase, spaces (except arc folder names like `A9 Desert`).

### Wikilinks & Linking Rules

Use `[[slug-name]]` — match exact filename without extension. Every entity must link to ≥1 other. No orphans.

| Entity | Required links |
|--------|---------------|
| npc | location, faction, or quest |
| quest | NPC + location |
| location | NPC or faction |
| faction | NPC + location |
| item | quest or owner NPC |
| encounter | location + creature |

### Logging

**Log format:** `[YYYY-MM-DD HH:mm:ss] [<task-id>] <message>`

| File | Content |
|------|---------|
| `system/logs/automation.log` | Consolidated all-agent log |
| `system/logs/<script-basename>_YYYY-MM-DD.log` | Per-script daily rotation |

Every script emits `--- START ---` and `--- DONE ---`. `--- DONE ---` format:
`--- DONE (classified: N, failed: N, elapsed: N.Ns) ---`

**Encoding:** All file I/O must use UTF-8. BOM stripping required when reading JSON files.

### Security Constraints

- No agent may self-approve content (`reviewed: true` — human-only)
- No agent may write to `02-Library/` without `reviewed: true` already set by human
- No agent may delete files from `00-Inbox/`
- Breaking canon requires explicit human git commit with reason in message
- LLM endpoints are localhost-only; no external API keys required

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ROADMAP -->
## Roadmap

- [x] Agent pipeline (ingestion → vision → lore → token → classification)
- [x] Wikilink graph generation
- [x] Token frame management + face cropping
- [x] Dashboard with live agent monitoring
- [ ] Relationship map auto-rendering in `04-Relationships/`
- [ ] Multi-campaign workspace switching
- [ ] Battlemap generation agent

See the [open issues](https://github.com/rodrigoazlima/NexusCampaigns/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Top contributors:

<a href="https://github.com/rodrigoazlima/NexusCampaigns/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=rodrigoazlima/NexusCampaigns" alt="contrib.rocks image" />
</a>

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- LICENSE -->
## License

Distributed under the project license. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Rodrigo Lima - rodrigoazlima@gmail.com

Project Link: [https://github.com/rodrigoazlima/NexusCampaigns](https://github.com/rodrigoazlima/NexusCampaigns)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* [Best-README-Template](https://github.com/othneildrew/Best-README-Template)
* [Obsidian](https://obsidian.md)
* [Anthropic Claude API](https://docs.anthropic.com)
* [Img Shields](https://shields.io)
* [Choose an Open Source License](https://choosealicense.com)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/rodrigoazlima/NexusCampaigns.svg?style=for-the-badge
[contributors-url]: https://github.com/rodrigoazlima/NexusCampaigns/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/rodrigoazlima/NexusCampaigns.svg?style=for-the-badge
[forks-url]: https://github.com/rodrigoazlima/NexusCampaigns/network/members
[stars-shield]: https://img.shields.io/github/stars/rodrigoazlima/NexusCampaigns.svg?style=for-the-badge
[stars-url]: https://github.com/rodrigoazlima/NexusCampaigns/stargazers
[issues-shield]: https://img.shields.io/github/issues/rodrigoazlima/NexusCampaigns.svg?style=for-the-badge
[issues-url]: https://github.com/rodrigoazlima/NexusCampaigns/issues
[license-shield]: https://img.shields.io/github/license/rodrigoazlima/NexusCampaigns.svg?style=for-the-badge
[license-url]: https://github.com/rodrigoazlima/NexusCampaigns/blob/master/LICENSE
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/rodrigoazlima
[Next.js]: https://img.shields.io/badge/next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white
[Next-url]: https://nextjs.org/
[React.js]: https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB
[React-url]: https://reactjs.org/
[TypeScript.com]: https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white
[TypeScript-url]: https://www.typescriptlang.org/
[Tailwind.com]: https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white
[Tailwind-url]: https://tailwindcss.com/
[Python.com]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://www.python.org/
[Anthropic.com]: https://img.shields.io/badge/Anthropic-191919?style=for-the-badge&logo=anthropic&logoColor=white
[Anthropic-url]: https://www.anthropic.com/
