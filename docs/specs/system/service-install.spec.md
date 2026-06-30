# Spec — Service Installation

---

## Overview

The pipeline runs as a long-lived OS service that executes one scheduling loop:

```
OS service supervisor
  └─ python .agents/runtime/tools/runner.py
       └─ every 60s: check agent.json → dispatch due agents → git commit
```

the runtime is the only process the service manages. All agents are
spawned as subprocesses by the runtime and run to completion.

---

## Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Python | 3.11 | Must be on `PATH` or absolute path used in service command |
| pip dependencies | see `requirements.txt` | Install before registering the service |
| Git | 2.x | On `PATH`; required for post-run commits |
| LLM server | reachable at configured endpoint | Vision + text endpoints (see `llm-integration.spec.md`) |

Install dependencies before registering the service:

```sh
pip install -r requirements.txt
```

Verify the runner executes successfully once before installing:

```sh
python .agents/runtime/tools/runner.py --once
```

A clean run produces `--- START ---` and `--- DONE ---` in
`.agents/runtime/state/logs/automation.log`.

---

## Service Identity

| Property | Value |
|----------|-------|
| **Name** | `vault-knowledge-factory` |
| **Display name** | Vault Nexus Campaigns |
| **Description** | DM pipeline — ingests, classifies, and links vault entities on schedule |
| **Entry command** | `python <project_root>/.agents/runtime/tools/runner.py` |
| **Working directory** | `<project_root>` (repo root, not `.agents/`) |
| **Restart policy** | Always; delay 30s on failure |
| **Start type** | Automatic (start on boot) |

Replace `<project_root>` with the absolute path to the repository root in
all commands below.

---

## Required Environment Variables

Set these in the service environment (not the shell profile — services do not
source shell init files):

| Variable | Example | Purpose |
|----------|---------|---------|
| `GIT_AUTHOR_NAME` | `Vault Bot` | Git identity for auto-commits |
| `GIT_AUTHOR_EMAIL` | `bot@localhost` | Git identity for auto-commits |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Required if any agent uses `claude-api` dispatch |
| `OPENAI_API_KEY` | `lm-studio` | Required for `openai-api` dispatch (set to any non-empty string for local endpoints) |
| `GEMINI_API_KEY` | `...` | Required if any agent uses `gemini-api` dispatch |
| `OPENROUTER_API_KEY` | `...` | Required if any agent uses `openrouter-api` dispatch |

**LLM endpoints and model identifiers** are configured in `registry.yaml` under `llm_endpoints` — not environment variables. Only API authentication keys come from env vars.

`vault_root` is configured in `registry.yaml`. It does not need to be set as an env var unless you want to override the registry value.

---

## Installation

### Windows — NSSM

NSSM (Non-Sucking Service Manager) wraps any executable as a Windows
service with restart policies and I/O redirection.

Download: https://nssm.cc/download — place `nssm.exe` on `PATH` or
reference by absolute path.

```bat
REM Run as Administrator
nssm install vault-knowledge-factory python
nssm set vault-knowledge-factory AppParameters ^
    "<project_root>\.agents\runtime\tools\runner.py"
nssm set vault-knowledge-factory AppDirectory "<project_root>"
nssm set vault-knowledge-factory DisplayName "Vault Nexus Campaigns"
nssm set vault-knowledge-factory Description ^
    "DM pipeline - ingests, classifies, and links vault entities on schedule"
nssm set vault-knowledge-factory Start SERVICE_AUTO_START
nssm set vault-knowledge-factory AppRestartDelay 30000
nssm set vault-knowledge-factory AppStdout ^
    "<project_root>\.agents\runtime\state\logs\service-stdout.log"
nssm set vault-knowledge-factory AppStderr ^
    "<project_root>\.agents\runtime\state\logs\service-stderr.log"

REM Set environment variables
nssm set vault-knowledge-factory AppEnvironmentExtra ^
    "GIT_AUTHOR_NAME=Vault Bot" ^
    "GIT_AUTHOR_EMAIL=bot@localhost" ^
    "ANTHROPIC_API_KEY=<your-key>"

nssm start vault-knowledge-factory
```

### Windows — Task Scheduler (no NSSM)

For environments where installing NSSM is not permitted, use Task Scheduler
with a wrapper script.

Create `.agents/runtime/tools/daemon.ps1`:
```powershell
while ($true) {
    python "<project_root>/.agents/runtime/tools/runner.py" --once
    Start-Sleep -Seconds 60
}
```

Register via `schtasks`:
```bat
schtasks /create /tn "VaultKnowledgeFactory" ^
    /tr "powershell -NonInteractive -File <project_root>\.agents\runtime\tools\daemon.ps1" ^
    /sc ONSTART /ru SYSTEM /f
```

> **Note:** Task Scheduler does not supervise long-running processes the same
> way a service supervisor does. Prefer NSSM for production installs.

---

### Linux — systemd

Create `/etc/systemd/system/vault-knowledge-factory.service`:

```ini
[Unit]
Description=Vault Nexus Campaigns
After=network.target
Wants=network.target

[Service]
Type=simple
User=<service_user>
WorkingDirectory=<project_root>
ExecStart=/usr/bin/python3 <project_root>/.agents/runtime/tools/runner.py
Restart=always
RestartSec=30

Environment=GIT_AUTHOR_NAME=Vault Bot
Environment=GIT_AUTHOR_EMAIL=bot@localhost
Environment=ANTHROPIC_API_KEY=<your-key>

StandardOutput=append:<project_root>/.agents/runtime/state/logs/service-stdout.log
StandardError=append:<project_root>/.agents/runtime/state/logs/service-stderr.log

[Install]
WantedBy=multi-user.target
```

Enable and start:

```sh
sudo systemctl daemon-reload
sudo systemctl enable vault-knowledge-factory
sudo systemctl start vault-knowledge-factory
```

---

### macOS — launchd

Create `~/Library/LaunchAgents/com.vaultknowledgefactory.plist`
(user agent) or `/Library/LaunchDaemons/com.vaultknowledgefactory.plist`
(system daemon — requires root):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.vaultknowledgefactory</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string><project_root>/.agents/runtime/tools/runner.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string><project_root></string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>GIT_AUTHOR_NAME</key>  <string>Vault Bot</string>
        <key>GIT_AUTHOR_EMAIL</key> <string>bot@localhost</string>
        <key>ANTHROPIC_API_KEY</key> <string><your-key></string>
    </dict>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string><project_root>/.agents/runtime/state/logs/service-stdout.log</string>
    <key>StandardErrorPath</key>
    <string><project_root>/.agents/runtime/state/logs/service-stderr.log</string>

    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
```

Load:

```sh
launchctl load ~/Library/LaunchAgents/com.vaultknowledgefactory.plist
```

---

## Verification

After starting the service, verify it is running correctly:

**1 — Process is alive:**

```sh
# Linux / macOS
pgrep -a python | grep runner.py

# Windows
tasklist | findstr python
```

**2 — Lock file exists** (created on first cycle, removed when the process exits cleanly):

```sh
# Should exist while running:
<project_root>/.agents/runtime/state/runner.lock
```

**3 — Log output:**

```sh
# Tail the master log
tail -f <project_root>/.agents/runtime/state/logs/automation.log
```

Expected output pattern on each cycle:
```
[2026-06-10 08:00:01] [runtime] INFO: --- START ---
[2026-06-10 08:00:01] [runtime] INFO: Skip ingestion-agent — not yet due
[2026-06-10 08:00:02] [runtime] INFO: Dispatching review-agent (...)
[2026-06-10 08:00:04] [runtime] INFO: --- DONE --- processed=1 failed=0 elapsed=2.1s
```

**4 — Service status per platform:**

```sh
# systemd
sudo systemctl status vault-knowledge-factory

# macOS
launchctl list | grep vaultknowledgefactory

# Windows (NSSM)
nssm status vault-knowledge-factory
```

---

## Uninstallation

Stop the service before uninstalling. The vault content and state files are
**not removed** by uninstall steps — they must be deleted manually if desired.

### Windows — NSSM

```bat
REM Run as Administrator
nssm stop vault-knowledge-factory
nssm remove vault-knowledge-factory confirm
```

### Windows — Task Scheduler

```bat
schtasks /delete /tn "VaultKnowledgeFactory" /f
```

### Linux — systemd

```sh
sudo systemctl stop vault-knowledge-factory
sudo systemctl disable vault-knowledge-factory
sudo rm /etc/systemd/system/vault-knowledge-factory.service
sudo systemctl daemon-reload
```

### macOS — launchd

```sh
launchctl unload ~/Library/LaunchAgents/com.vaultknowledgefactory.plist
rm ~/Library/LaunchAgents/com.vaultknowledgefactory.plist
```

---

## Upgrade Procedure

1. Stop the service.
2. Pull or deploy the new code.
3. Install any new dependencies: `pip install -r requirements.txt`.
4. Run `python .agents/runtime/tools/runner.py --once` manually to
   verify the new version starts cleanly.
5. Start the service.

If `agent.json` gained new tasks, add matching entries to `tasks-state.json`
with `lastRun: "1970-01-01T00:00:00+00:00"` before starting (forces
immediate first run of the new agent).

---

## Stale Lock Recovery

If the service crashes while holding the lock, the next startup detects a
stale lock (age > 1800s) and overrides it automatically. No manual
intervention is required.

To force-clear a stale lock manually:

```sh
rm <project_root>/.agents/runtime/state/runner.lock
```

---

## Log Rotation

Log files accumulate under `.agents/runtime/state/logs/`. The Cleanup
Agent (daily) purges files older than `cleanupDays` (default: 90 days).

If the Cleanup Agent has not run, rotate manually:

```sh
# Delete daily logs older than 90 days
find <project_root>/.agents -name "*.log" -mtime +90 -delete
```

On Windows (PowerShell):

```powershell
Get-ChildItem -Path "<project_root>\.agents" -Filter "*.log" -Recurse |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
  Remove-Item -Force
```
