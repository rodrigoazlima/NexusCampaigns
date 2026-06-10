# Spec — Service Installation

---

## Overview

The pipeline runs as a long-lived OS service that executes one scheduling loop:

```
OS service supervisor
  └─ python .agents/orchestrator/tools/runner.py
       └─ every 60s: check tasks.json → dispatch due agents → git commit
```

The orchestrator is the only process the service manages. All agents are
spawned as subprocesses by the orchestrator and run to completion.

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
python .agents/orchestrator/tools/runner.py --once
```

A clean run produces `--- START ---` and `--- DONE ---` in
`.agents/orchestrator/state/logs/automation.log`.

---

## Service Identity

| Property | Value |
|----------|-------|
| **Name** | `vault-knowledge-factory` |
| **Display name** | Vault Knowledge Factory |
| **Description** | DM pipeline — ingests, classifies, and links vault entities on schedule |
| **Entry command** | `python <project_root>/.agents/orchestrator/tools/runner.py` |
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
| `VAULT_ROOT` | `/opt/campaigns/knowledge-base` | Absolute path to `knowledge-base/` |
| `LLM_TEXT_URL` | `http://localhost:11434` | Text LLM base URL |
| `LLM_VISION_URL` | `http://localhost:11435` | Vision LLM base URL |
| `LLM_TEXT_MODEL` | `mistral:7b` | Text model identifier |
| `LLM_VISION_MODEL` | `llava:13b` | Vision model identifier |
| `GIT_AUTHOR_NAME` | `Vault Bot` | Git identity for auto-commits |
| `GIT_AUTHOR_EMAIL` | `bot@localhost` | Git identity for auto-commits |

Variables are consumed by `shared.loaders.load_vault_config()` at agent
startup. Missing required variables cause the agent to exit with code 1
before processing any files.

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
    "<project_root>\.agents\orchestrator\tools\runner.py"
nssm set vault-knowledge-factory AppDirectory "<project_root>"
nssm set vault-knowledge-factory DisplayName "Vault Knowledge Factory"
nssm set vault-knowledge-factory Description ^
    "DM pipeline - ingests, classifies, and links vault entities on schedule"
nssm set vault-knowledge-factory Start SERVICE_AUTO_START
nssm set vault-knowledge-factory AppRestartDelay 30000
nssm set vault-knowledge-factory AppStdout ^
    "<project_root>\.agents\orchestrator\state\logs\service-stdout.log"
nssm set vault-knowledge-factory AppStderr ^
    "<project_root>\.agents\orchestrator\state\logs\service-stderr.log"

REM Set environment variables
nssm set vault-knowledge-factory AppEnvironmentExtra ^
    "VAULT_ROOT=<vault_root>" ^
    "LLM_TEXT_URL=http://localhost:11434" ^
    "LLM_VISION_URL=http://localhost:11435" ^
    "LLM_TEXT_MODEL=mistral:7b" ^
    "LLM_VISION_MODEL=llava:13b" ^
    "GIT_AUTHOR_NAME=Vault Bot" ^
    "GIT_AUTHOR_EMAIL=bot@localhost"

nssm start vault-knowledge-factory
```

### Windows — Task Scheduler (no NSSM)

For environments where installing NSSM is not permitted, use Task Scheduler
with a wrapper script.

Create `.agents/orchestrator/tools/daemon.ps1`:
```powershell
while ($true) {
    python "<project_root>/.agents/orchestrator/tools/runner.py" --once
    Start-Sleep -Seconds 60
}
```

Register via `schtasks`:
```bat
schtasks /create /tn "VaultKnowledgeFactory" ^
    /tr "powershell -NonInteractive -File <project_root>\.agents\orchestrator\tools\daemon.ps1" ^
    /sc ONSTART /ru SYSTEM /f
```

> **Note:** Task Scheduler does not supervise long-running processes the same
> way a service supervisor does. Prefer NSSM for production installs.

---

### Linux — systemd

Create `/etc/systemd/system/vault-knowledge-factory.service`:

```ini
[Unit]
Description=Vault Knowledge Factory
After=network.target
Wants=network.target

[Service]
Type=simple
User=<service_user>
WorkingDirectory=<project_root>
ExecStart=/usr/bin/python3 <project_root>/.agents/orchestrator/tools/runner.py
Restart=always
RestartSec=30

Environment=VAULT_ROOT=<vault_root>
Environment=LLM_TEXT_URL=http://localhost:11434
Environment=LLM_VISION_URL=http://localhost:11435
Environment=LLM_TEXT_MODEL=mistral:7b
Environment=LLM_VISION_MODEL=llava:13b
Environment=GIT_AUTHOR_NAME=Vault Bot
Environment=GIT_AUTHOR_EMAIL=bot@localhost

StandardOutput=append:<project_root>/.agents/orchestrator/state/logs/service-stdout.log
StandardError=append:<project_root>/.agents/orchestrator/state/logs/service-stderr.log

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
        <string><project_root>/.agents/orchestrator/tools/runner.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string><project_root></string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>VAULT_ROOT</key>       <string><vault_root></string>
        <key>LLM_TEXT_URL</key>     <string>http://localhost:11434</string>
        <key>LLM_VISION_URL</key>   <string>http://localhost:11435</string>
        <key>LLM_TEXT_MODEL</key>   <string>mistral:7b</string>
        <key>LLM_VISION_MODEL</key> <string>llava:13b</string>
        <key>GIT_AUTHOR_NAME</key>  <string>Vault Bot</string>
        <key>GIT_AUTHOR_EMAIL</key> <string>bot@localhost</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string><project_root>/.agents/orchestrator/state/logs/service-stdout.log</string>
    <key>StandardErrorPath</key>
    <string><project_root>/.agents/orchestrator/state/logs/service-stderr.log</string>

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
<project_root>/.agents/orchestrator/state/runner.lock
```

**3 — Log output:**

```sh
# Tail the master log
tail -f <project_root>/.agents/orchestrator/state/logs/automation.log
```

Expected output pattern on each cycle:
```
[2026-06-10 08:00:01] [orchestrator] INFO: --- START ---
[2026-06-10 08:00:01] [orchestrator] INFO: Skip ingestion-agent — not yet due
[2026-06-10 08:00:02] [orchestrator] INFO: Dispatching review-agent (...)
[2026-06-10 08:00:04] [orchestrator] INFO: --- DONE --- processed=1 failed=0 elapsed=2.1s
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
4. Run `python .agents/orchestrator/tools/runner.py --once` manually to
   verify the new version starts cleanly.
5. Start the service.

If `tasks.json` gained new tasks, add matching entries to `tasks-state.json`
with `lastRun: "1970-01-01T00:00:00+00:00"` before starting (forces
immediate first run of the new agent).

---

## Stale Lock Recovery

If the service crashes while holding the lock, the next startup detects a
stale lock (age > 1800s) and overrides it automatically. No manual
intervention is required.

To force-clear a stale lock manually:

```sh
rm <project_root>/.agents/orchestrator/state/runner.lock
```

---

## Log Rotation

Log files accumulate under `.agents/orchestrator/state/logs/`. The Cleanup
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
