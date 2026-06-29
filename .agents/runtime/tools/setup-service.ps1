# setup-service.ps1 — Install and start Nexus Campaigns services
#
# Installs pip deps, registers and starts the agent pipeline service, and builds,
# registers, and starts the Next.js dashboard on port 48080. Run once from elevated shell.
#
# Supported methods (auto-detected):
#   nssm      — NSSM service manager (requires Admin; recommended for production)
#   schtasks  — HKCU Run key (works without Admin; starts at logon)
#
# Usage (requires pwsh / PowerShell 7+):
#   # Install and start everything (run as Administrator):
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1
#
#   # Force a specific method:
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Method schtasks
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Method nssm
#
#   # Custom dashboard port (default 48080) / skip dashboard:
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -DashboardPort 9000
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -NoDashboard
#
#   # Opt in to runner --once pre-flight verification (~60s):
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -RunPreFlight
#
#   # Uninstall (removes both services):
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Uninstall
#
#   # Check status:
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Status
#
#   # Clean install (wipes generated state, indexes, configs, build artifacts, then installs fresh):
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -CleanInstall

param(
    [string] $ProjectRoot    = "C:\opt\GitHub\NexusCampaigns",
    [string] $Python         = "python",
    [string] $Method         = "auto",    # "auto" | "nssm" | "schtasks"
    [int]    $DashboardPort  = 48080,
    [switch] $NoDashboard,
    [switch] $Force,
    [switch] $Uninstall,
    [switch] $Status,
    [switch] $RunPreFlight,
    [switch] $CleanInstall,
    [switch] $Help
)

if ($Help) {
    Write-Host @"

setup-service.ps1 — Install and start Nexus Campaigns services

USAGE
  pwsh -ExecutionPolicy Bypass -File setup-service.ps1 [parameters]

PARAMETERS
  -ProjectRoot   <path>   Vault project root. Default: C:\opt\GitHub\NexusCampaigns
  -Python        <cmd>    Python executable to use. Default: python
  -Method        <str>    Install method: auto | nssm | schtasks. Default: auto
                            auto     — picks nssm when admin + NSSM installed, else schtasks
                            nssm     — Windows service via NSSM (requires Admin + NSSM)
                            schtasks — HKCU Run key; no admin needed, starts at logon
  -DashboardPort <int>    Next.js dashboard port. Default: read from global.json, else 48080
  -NoDashboard            Skip dashboard build and start entirely
  -Force                  Overwrite existing .env.local config (default: keep existing)
  -RunPreFlight           Run runner --once before installing (~60s pre-flight check)
  -Status                 Check if agent service and dashboard are running, then exit
  -Uninstall              Remove both services and all Run keys, kill lingering processes
  -CleanInstall           Wipe generated state/indexes/configs/build artifacts, then install fresh
                            Preserved: 00-Inbox, 02-Library, 03-Campaigns, 05-Assets, 99-Archive
                            Deleted:   01-Processing, 04-Relationships, agent state, logs, node_modules
                            Re-seeded: tasks-state.json (all agents → epoch), agent-metrics.json ({})
  -Help                   Show this help and exit

EXAMPLES
  # Default install (auto-detects method):
  pwsh -ExecutionPolicy Bypass -File setup-service.ps1

  # Force NSSM (must be Admin):
  pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Method nssm

  # Custom port, skip dashboard:
  pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -DashboardPort 9000 -NoDashboard

  # Check service health:
  pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Status

  # Full wipe + fresh install:
  pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -CleanInstall

  # Remove everything:
  pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Uninstall

LOGS
  .agents\runtime\state\logs\automation.log      — consolidated pipeline log
  .agents\runtime\state\logs\npm-build.log        — dashboard build output
  .agents\runtime\state\logs\nssm-install.log     — NSSM registration output

"@
    exit 0
}

$ErrorActionPreference = "Stop"

$ServiceName  = "vault-knowledge-factory"
$TaskName     = "VaultKnowledgeFactory"
$DisplayName  = "Vault Nexus Campaigns"
$Description  = "DM pipeline: ingests, classifies, and links vault entities on schedule"
$DaemonScript = "$ProjectRoot\.agents\runtime\tools\daemon.ps1"
$RunnerScript = "$ProjectRoot\.agents\runtime\tools\runner.py"
$LogDir       = "$ProjectRoot\.agents\runtime\state\logs"

$DashboardSvc = "vault-dashboard"                       # NSSM service name
$DashboardRun = "VaultDashboard"                        # HKCU Run value name
$DashboardDir = "$ProjectRoot\.system\dashboard"
$GlobalConfig = "$ProjectRoot\.system\.shared\config\global.json"

# ---------------------------------------------------------------------------
# Resolve defaults FROM the codebase config (.system/.shared/config/global.json)
# so the configuration is the single source of truth for ports + vault root.
# An explicit -DashboardPort still wins over the config value.
# ---------------------------------------------------------------------------
$DashboardHost = "0.0.0.0"
$VaultRootRel  = "knowledge-base"
if (Test-Path $GlobalConfig) {
    try {
        $gc = Get-Content $GlobalConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $PSBoundParameters.ContainsKey('DashboardPort') -and $gc.ports.dashboard) {
            $DashboardPort = [int]$gc.ports.dashboard
        }
        if ($gc.ports.host)  { $DashboardHost = [string]$gc.ports.host }
        if ($gc.vault_root)  { $VaultRootRel  = [string]$gc.vault_root }
    } catch {
        Write-Host "WARN: could not parse $GlobalConfig — using built-in defaults. $_"
    }
}
# Resolve vault root to an absolute path anchored at the project root.
$VaultRootAbs = if ([System.IO.Path]::IsPathRooted($VaultRootRel)) { $VaultRootRel }
                else { Join-Path $ProjectRoot $VaultRootRel }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Log([string]$Msg, [string]$Level = "INFO") {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] [setup-service] ${Level}: $Msg"
}

$script:ProgressPct = 0
function Step-Progress([string]$Status, [int]$Pct) {
    $script:ProgressPct = $Pct
    Write-Progress -Activity "Nexus Campaigns Setup" -Status $Status -PercentComplete $Pct
}

function Is-Admin {
    ([Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-NSSM {
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if ($nssm) { return $nssm.Source }
    # Common install locations
    foreach ($p in @(
        "C:\nssm\win64\nssm.exe",
        "C:\tools\nssm\nssm.exe",
        "$env:ProgramFiles\nssm\nssm.exe"
    )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Find-Node {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) { return $node.Source }
    foreach ($p in @(
        "$env:ProgramFiles\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\nodejs\node.exe"
    )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

# Produce the canonical env config at .system\.env.local, derived from global.json.
# Does not clobber an existing file unless -Force is given.
# Callers that need the file in the dashboard dir must copy it there explicitly.
function Write-DefaultConfig {
    $systemDir = "$ProjectRoot\.system"
    $envFile   = "$systemDir\.env.local"

    if (-not (Test-Path $systemDir)) {
        Log "System dir not found: $systemDir — skipping config generation." "WARN"
        return
    }
    if ((Test-Path $envFile) -and -not $Force) {
        Log "Default config already exists: $envFile (use -Force to regenerate). Keeping it."
        return
    }

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $lines = @(
        "# Generated by setup-service.ps1 on $stamp",
        "# Canonical env config — source of truth for ports + vault root.",
        "# Change ports.dashboard in .system/.shared/config/global.json and re-run setup -Force.",
        "PROJECT_ROOT=$ProjectRoot",
        "VAULT_ROOT=$VaultRootAbs",
        "PORT=$DashboardPort",
        "HOSTNAME=$DashboardHost"
    )
    Set-Content -Path $envFile -Value $lines -Encoding UTF8
    Log "Produced config: $envFile"
    Log "  PROJECT_ROOT=$ProjectRoot"
    Log "  VAULT_ROOT=$VaultRootAbs"
    Log "  PORT=$DashboardPort  HOSTNAME=$DashboardHost"
}

# Build the dashboard and register it to run on $DashboardPort.
# Uses NSSM service (admin) when available, otherwise an HKCU Run key + detached start.
function Setup-Dashboard {
    param([string]$Method)

    Log "=== Dashboard setup (port $DashboardPort) ==="

    if (-not (Test-Path $DashboardDir)) {
        Log "Dashboard dir not found: $DashboardDir — skipping." "WARN"
        return
    }

    $nodePath = Find-Node
    if (-not $nodePath) {
        Log "Node.js not found — install Node 18+ and re-run. Skipping dashboard." "WARN"
        return
    }
    $npm = Join-Path (Split-Path $nodePath) "npm.cmd"
    Log "Node: $nodePath"

    # Copy canonical env config into the dashboard dir (Next.js reads .env.local from its project root)
    $canonicalEnv = "$ProjectRoot\.system\.env.local"
    $dashEnv      = "$DashboardDir\.env.local"
    if (Test-Path $canonicalEnv) {
        Copy-Item $canonicalEnv $dashEnv -Force
        Log "Copied .system\.env.local -> .system\dashboard\.env.local"
    } else {
        Log ".system\.env.local not found — run Write-DefaultConfig first." "WARN"
    }

    # Install deps + production build
    Push-Location $DashboardDir
    try {
        $npmLog = "$LogDir\npm-install.log"
        Step-Progress "Installing dashboard npm dependencies..." 65
        Log "Installing dashboard dependencies (npm install → $npmLog)..."
        & $npm install 2>&1 | Out-File $npmLog -Encoding UTF8
        if ($LASTEXITCODE -ne 0) { Log "npm install failed — check $npmLog" "ERROR"; return }
        $buildLog = "$LogDir\npm-build.log"
        Step-Progress "Building dashboard (npm run build)..." 75
        Log "Building dashboard (npm run build → $buildLog)..."
        & $npm run build 2>&1 | Out-File $buildLog -Encoding UTF8
        if ($LASTEXITCODE -ne 0) { Log "npm run build failed — check $buildLog" "ERROR"; return }
    } finally {
        Pop-Location
    }

    $nextBin = "$DashboardDir\node_modules\next\dist\bin\next"

    if ($Method -eq "nssm") {
        $nssmPath = Find-NSSM
        $existing = Get-Service -Name $DashboardSvc -ErrorAction SilentlyContinue
        if ($existing) {
            Log "Removing existing dashboard service '$DashboardSvc'..."
            if ($existing.Status -eq "Running") { & $nssmPath stop $DashboardSvc }
            & $nssmPath remove $DashboardSvc confirm
        }
        Log "Installing NSSM service '$DashboardSvc' (details: $nssmLog)..."
        & $nssmPath install $DashboardSvc $nodePath                                                                          2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppParameters  "`"$nextBin`" start --port $DashboardPort --hostname $DashboardHost" 2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppDirectory   $DashboardDir                                                       2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc DisplayName    "Vault Nexus Dashboard"                                             2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc Description    "Nexus Campaigns admin dashboard (Next.js) on port $DashboardPort"  2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc Start          SERVICE_AUTO_START                                                  2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppRestartDelay 30000                                                              2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppStdout      "$LogDir\dashboard-stdout.log"                                      2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppStderr      "$LogDir\dashboard-stderr.log"                                      2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppStdoutCreationDisposition 4                                                     2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppStderrCreationDisposition 4                                                     2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        & $nssmPath set     $DashboardSvc AppEnvironmentExtra "NODE_ENV=production PORT=$DashboardPort HOSTNAME=$DashboardHost" 2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        Step-Progress "Starting dashboard service..." 90
        Log "Starting dashboard service '$DashboardSvc'..."
        & $nssmPath start $DashboardSvc 2>&1 | Out-File $nssmLog -Append -Encoding UTF8
        Log "Dashboard started -> http://localhost:$DashboardPort"
    } else {
        # No admin: auto-start at logon via HKCU Run key + start now (detached, hidden).
        $RegPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
        $cmd     = "`"$nodePath`" `"$nextBin`" start --port $DashboardPort --hostname $DashboardHost"
        $existing = Get-ItemProperty $RegPath -Name $DashboardRun -ErrorAction SilentlyContinue
        if ($existing) { Remove-ItemProperty $RegPath -Name $DashboardRun -Force }
        Set-ItemProperty $RegPath -Name $DashboardRun -Value $cmd
        Log "Dashboard auto-start registered: HKCU\...\Run\$DashboardRun"
        $proc = Start-Process -FilePath $nodePath `
            -ArgumentList @($nextBin, "start", "--port", "$DashboardPort", "--hostname", "$DashboardHost") `
            -WorkingDirectory $DashboardDir -WindowStyle Hidden -PassThru
        if ($proc) { Log "Dashboard started (PID=$($proc.Id)) -> http://localhost:$DashboardPort" }
        else       { Log "Dashboard Start-Process returned no handle — may have launched detached." "WARN" }
    }
}

function Get-AuthToken {
    if ($env:ANTHROPIC_API_KEY)  { return @{ Var = "ANTHROPIC_API_KEY";  Value = $env:ANTHROPIC_API_KEY } }
    if ($env:ANTHROPIC_AUTH_TOKEN) { return @{ Var = "ANTHROPIC_AUTH_TOKEN"; Value = $env:ANTHROPIC_AUTH_TOKEN } }

    $credsFile = "$env:USERPROFILE\.claude\.credentials.json"
    if (Test-Path $credsFile) {
        try {
            $creds = Get-Content $credsFile -Raw | ConvertFrom-Json
            $token = $creds.claudeAiOauth.accessToken
            if ($token) { return @{ Var = "ANTHROPIC_AUTH_TOKEN"; Value = $token } }
        } catch {}
    }
    return $null
}

# ---------------------------------------------------------------------------
# Validation — assert all services are healthy (port + HTTP + PID checks)
# ---------------------------------------------------------------------------

function Assert-ServicesRunning {
    param([switch]$WaitForStartup)

    $ok = $true

    # Poll up to 30s for dashboard port after a fresh start
    if ($WaitForStartup -and -not $NoDashboard) {
        Log "Waiting for dashboard to become ready (up to 30s)..."
        $elapsed = 0
        do {
            Start-Sleep -Seconds 2
            $elapsed += 2
            $ready = Get-NetTCPConnection -State Listen -LocalPort $DashboardPort -ErrorAction SilentlyContinue
        } while (-not $ready -and $elapsed -lt 30)
        if ($ready) { Log "Dashboard port $DashboardPort responded after ${elapsed}s." }
        else         { Log "Dashboard port $DashboardPort did not respond within 30s — proceeding with validation." "WARN" }
    }

    Log "--- Service Validation ---"

    # Agent service (NSSM) or daemon process (schtasks)
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        if ($svc.Status -eq "Running") {
            Log "  [PASS] Agent service '$ServiceName': Running"
        } else {
            Log "  [FAIL] Agent service '$ServiceName': $($svc.Status)" "ERROR"
            $ok = $false
        }
    } else {
        $daemonProcs = @(Get-Process powershell, pwsh -ErrorAction SilentlyContinue |
                         Where-Object { $_.CommandLine -like "*daemon.ps1*" })
        if ($daemonProcs.Count -gt 0) {
            Log "  [PASS] Daemon process(es) running — PIDs: $($daemonProcs.Id -join ', ')"
        } else {
            Log "  [WARN] Daemon process not detected (HKCU Run key starts at next login)" "WARN"
        }
    }

    # Runner process (active mid-cycle only — absence between cycles is normal)
    $runnerProcs = @(Get-Process python -ErrorAction SilentlyContinue |
                     Where-Object { $_.CommandLine -like "*runner.py*" })
    if ($runnerProcs.Count -gt 0) {
        Log "  [PASS] Runner process(es) active — PIDs: $($runnerProcs.Id -join ', ')"
    } else {
        Log "  [INFO] Runner not active (normal between cycles)"
    }

    # Lock file PID liveness
    $lockFile = "$ProjectRoot\.agents\runtime\state\runner.lock"
    if (Test-Path $lockFile) {
        try {
            $ld = Get-Content $lockFile -Raw | ConvertFrom-Json
            $lp = Get-Process -Id ([int]$ld.pid) -ErrorAction SilentlyContinue
            if ($lp) { Log "  [PASS] Lock PID $($ld.pid) alive ($($lp.Name))" }
            else      { Log "  [WARN] Lock PID $($ld.pid) is dead — stale lock file" "WARN" }
        } catch { Log "  [WARN] Lock file parse error: $_" "WARN" }
    } else {
        Log "  [INFO] Lock file absent (runner not mid-cycle)"
    }

    # Dashboard NSSM service status (informational — port+HTTP are authoritative)
    $dsvc = Get-Service -Name $DashboardSvc -ErrorAction SilentlyContinue
    if ($dsvc) {
        if ($dsvc.Status -eq "Running") {
            Log "  [PASS] Dashboard service '$DashboardSvc': Running"
        } else {
            Log "  [WARN] Dashboard service '$DashboardSvc': $($dsvc.Status) (port+HTTP checks are authoritative)" "WARN"
        }
    }

    # Dashboard port + HTTP probe
    if (-not $NoDashboard) {
        $tcp = Get-NetTCPConnection -State Listen -LocalPort $DashboardPort -ErrorAction SilentlyContinue
        if ($tcp) {
            $ownerPid  = ($tcp | Select-Object -First 1).OwningProcess
            $ownerProc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            Log "  [PASS] Dashboard port $DashboardPort listening — PID=$ownerPid ($($ownerProc.Name))"
            try {
                $r = Invoke-WebRequest -Uri "http://localhost:$DashboardPort" -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
                Log "  [PASS] Dashboard HTTP $($r.StatusCode) OK -> http://localhost:$DashboardPort"
            } catch {
                Log "  [WARN] Dashboard HTTP probe failed: $($_.Exception.Message)" "WARN"
            }
        } else {
            Log "  [FAIL] Dashboard port $DashboardPort not listening" "ERROR"
            $ok = $false
        }
    }

    if ($ok) { Log "--- Validation PASSED ---" }
    else      { Log "--- Validation FAILED — review errors above ---" "ERROR" }

    return $ok
}

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

if ($Status) {
    if (-not (Assert-ServicesRunning)) { exit 1 }
    exit 0
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

if ($Uninstall) {
    Log "Uninstalling $DisplayName..."

    # Stop + remove NSSM service
    $nssmPath = Find-NSSM
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $nssmPath) {
        if ($svc.Status -eq "Running") {
            Log "Stopping NSSM service..."
            & $nssmPath stop $ServiceName
        }
        Log "Removing NSSM service..."
        & $nssmPath remove $ServiceName confirm
        Log "NSSM service removed."
    }

    # Remove HKCU Run key (schtasks method)
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $runVal  = Get-ItemProperty $regPath -Name $TaskName -ErrorAction SilentlyContinue
    if ($runVal) {
        Remove-ItemProperty $regPath -Name $TaskName -Force
        Log "HKCU Run key '$TaskName' removed."
    }

    # Remove dashboard service + run key
    $dsvc = Get-Service -Name $DashboardSvc -ErrorAction SilentlyContinue
    if ($dsvc -and $nssmPath) {
        if ($dsvc.Status -eq "Running") { Log "Stopping dashboard service..."; & $nssmPath stop $DashboardSvc }
        Log "Removing dashboard service..."
        & $nssmPath remove $DashboardSvc confirm
    }
    $dRun = Get-ItemProperty $regPath -Name $DashboardRun -ErrorAction SilentlyContinue
    if ($dRun) {
        Remove-ItemProperty $regPath -Name $DashboardRun -Force
        Log "HKCU Run key '$DashboardRun' removed."
    }
    # Stop any next.js dashboard process bound to the port
    $dProc = Get-NetTCPConnection -State Listen -LocalPort $DashboardPort -ErrorAction SilentlyContinue
    if ($dProc) {
        $dProc.OwningProcess | Sort-Object -Unique | ForEach-Object {
            Log "Stopping dashboard process PID=$_"
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    }

    # Kill any lingering daemon/runner processes
    Get-Process powershell, python -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*daemon.ps1*" -or $_.CommandLine -like "*runner.py*" } |
        ForEach-Object { Log "Stopping process PID=$($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

    Log "Uninstall complete."
    exit 0
}

# ---------------------------------------------------------------------------
# Clean Install — wipe all generated state, indexes, configs, and build artifacts
# Only executes when -CleanInstall is passed. Requires explicit confirmation.
# Preserves: 00-Inbox (source material), 02-Library (approved), 05-Assets (approved)
# ---------------------------------------------------------------------------

if ($CleanInstall) {
    Write-Host ""
    Write-Host "  !! CLEAN INSTALL !!" -ForegroundColor Yellow
    Write-Host "  This will permanently delete:" -ForegroundColor Yellow
    Write-Host "    - Dashboard node_modules and .next build cache" -ForegroundColor Yellow
    Write-Host "    - All agent state files, indexes, and log files" -ForegroundColor Yellow
    Write-Host "    - All .env.local config files" -ForegroundColor Yellow
    Write-Host "    - 01-Processing drafts (pending review)" -ForegroundColor Yellow
    Write-Host "    - 04-Relationships (auto-generated graphs)" -ForegroundColor Yellow
    Write-Host "  Re-created with defaults: tasks-state.json (epoch), agent-metrics.json (empty)" -ForegroundColor Cyan
    Write-Host "  Preserved: 00-Inbox, 02-Library, 03-Campaigns, 05-Assets, 99-Archive" -ForegroundColor Green
    Write-Host ""
    $confirm = Read-Host "  Type 'yes' to confirm clean install"
    if ($confirm -ne 'yes') {
        Write-Host "Clean install cancelled." -ForegroundColor Cyan
        exit 0
    }

    Log "=== CLEAN INSTALL: wiping generated state ==="

    # 1. Dashboard build artifacts
    foreach ($dir in @("$DashboardDir\node_modules", "$DashboardDir\.next")) {
        if (Test-Path $dir) {
            Log "Removing $dir ..."
            Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    # 2. Agent runtime state (logs, metrics, locks, task state, generated indexes)
    $agentStateDir = "$ProjectRoot\.agents\runtime\state"
    if (Test-Path $agentStateDir) {
        Log "Removing agent runtime state: $agentStateDir ..."
        Remove-Item $agentStateDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    # 3. Per-agent state directories (vision, token, review, etc.)
    foreach ($agentDir in Get-ChildItem "$ProjectRoot\.agents" -Directory -ErrorAction SilentlyContinue) {
        $stateDir = Join-Path $agentDir.FullName "state"
        if (Test-Path $stateDir) {
            Log "Removing agent state: $stateDir ..."
            Remove-Item $stateDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    # 4. Shared system state
    $sharedState = "$ProjectRoot\.system\state"
    if (Test-Path $sharedState) {
        Log "Removing shared system state: $sharedState ..."
        Remove-Item $sharedState -Recurse -Force -ErrorAction SilentlyContinue
    }

    # 5. Env config files
    foreach ($envFile in @(
        "$ProjectRoot\.system\.env.local",
        "$DashboardDir\.env.local"
    )) {
        if (Test-Path $envFile) {
            Log "Removing config: $envFile ..."
            Remove-Item $envFile -Force -ErrorAction SilentlyContinue
        }
    }

    # 6. Vault pipeline dirs (generated content only — NOT source/approved content)
    $VaultRootForClean = if ([System.IO.Path]::IsPathRooted($VaultRootRel)) { $VaultRootRel }
                         else { Join-Path $ProjectRoot $VaultRootRel }
    foreach ($vaultDir in @("01-Processing", "04-Relationships")) {
        $target = Join-Path $VaultRootForClean $vaultDir
        if (Test-Path $target) {
            Log "Clearing vault dir: $target ..."
            Get-ChildItem $target -File -Recurse -ErrorAction SilentlyContinue |
                ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
        }
    }

    # 7. Re-create runtime state dir + seed JSON files with clean defaults
    $cleanStateDir = "$ProjectRoot\.agents\runtime\state"
    New-Item -ItemType Directory -Force $cleanStateDir | Out-Null
    New-Item -ItemType Directory -Force "$cleanStateDir\logs" | Out-Null

    # tasks-state.json — scan all agent.json files for task IDs, set all to epoch
    $epoch      = "1970-01-01T00:00:00Z"
    $tasksState = [ordered]@{}
    Get-ChildItem "$ProjectRoot\.agents" -Recurse -Filter "agent.json" -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                $aj = Get-Content $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($aj.tasks) {
                    $aj.tasks.PSObject.Properties.Name | ForEach-Object {
                        $tasksState[$_] = [ordered]@{ lastRun = $epoch }
                    }
                }
            } catch { Log "Could not parse $($_.FullName): $_" "WARN" }
        }
    $tasksState | ConvertTo-Json -Depth 3 |
        Set-Content "$cleanStateDir\tasks-state.json" -Encoding UTF8
    Log "Re-created tasks-state.json ($($tasksState.Count) agents → epoch)."

    # agent-metrics.json — empty slate
    '{}' | Set-Content "$cleanStateDir\agent-metrics.json" -Encoding UTF8
    Log "Re-created agent-metrics.json (empty)."

    Log "Clean complete. Proceeding with fresh install..."
    Write-Host ""

    # Force config regeneration since we wiped the old one
    $Force = $true
}

# ---------------------------------------------------------------------------
# Remove any previous install before fresh install
# ---------------------------------------------------------------------------

Log "=== Vault Nexus Campaigns — Service Setup ==="
Step-Progress "Removing previous installation..." 5
Log "Checking for previous installation to remove..."

$_nssmPath = Find-NSSM

# Remove NSSM services if present
foreach ($svcName in @($ServiceName, $DashboardSvc)) {
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if ($svc) {
        Log "Removing previous service '$svcName' (status: $($svc.Status))..."
        if ($svc.Status -eq "Running" -and $_nssmPath) { & $_nssmPath stop $svcName }
        elseif ($svc.Status -eq "Running")             { Stop-Service $svcName -Force -ErrorAction SilentlyContinue }
        if ($_nssmPath) { & $_nssmPath remove $svcName confirm }
        else            { sc.exe delete $svcName | Out-Null }
        Log "  Removed: $svcName"
    }
}

# Remove HKCU Run keys if present
$_regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
foreach ($keyName in @($TaskName, $DashboardRun)) {
    $val = Get-ItemProperty $_regPath -Name $keyName -ErrorAction SilentlyContinue
    if ($val) {
        Remove-ItemProperty $_regPath -Name $keyName -Force
        Log "  Removed Run key: $keyName"
    }
}

# Stop any lingering runner/daemon processes
Get-Process powershell, pwsh, python -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*daemon.ps1*" -or $_.CommandLine -like "*runner.py*" } |
    ForEach-Object { Log "  Stopping process PID=$($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

# Free the dashboard port. A stale process squatting $DashboardPort (e.g. a manual
# `next start` from a prior session, NOT a managed service) survives service removal
# above and makes the new NSSM service hit EADDRINUSE → stuck PAUSED, while the dead
# process keeps serving an old .next whose chunk hashes no longer match → ChunkLoadError
# 500 in the browser. Kill whatever still holds the port before (re)installing.
if (-not $NoDashboard) {
    $portHold = Get-NetTCPConnection -State Listen -LocalPort $DashboardPort -ErrorAction SilentlyContinue
    if ($portHold) {
        $portHold.OwningProcess | Sort-Object -Unique | ForEach-Object {
            $hp = Get-Process -Id $_ -ErrorAction SilentlyContinue
            Log "  Freeing port ${DashboardPort}: stopping PID=$_ ($($hp.Name))"
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
Step-Progress "Checking prerequisites..." 15
Log "ProjectRoot : $ProjectRoot"
Log "Python      : $Python"

# Verify project root exists
if (-not (Test-Path $ProjectRoot)) {
    Log "ProjectRoot '$ProjectRoot' not found." "ERROR"
    exit 1
}

# Verify runner script exists
if (-not (Test-Path $RunnerScript)) {
    Log "Runner script not found: $RunnerScript" "ERROR"
    exit 1
}

# Verify Python
try {
    $pyVer = & $Python --version 2>&1
    Log "Python: $pyVer"
} catch {
    Log "Python not found at '$Python'. Install Python 3.11+ and add to PATH." "ERROR"
    exit 1
}

Step-Progress "Installing Python dependencies..." 25
Log "Installing pip dependencies..."
& $Python -m pip install -r "$ProjectRoot\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) {
    Log "pip install failed — check requirements.txt." "ERROR"
    exit 1
}
Log "Dependencies OK."

# Auth token
$auth = Get-AuthToken
if ($auth) {
    Log "Auth: using $($auth.Var)"
} else {
    Log "WARNING: No ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN found." "WARN"
    Log "         Set ANTHROPIC_API_KEY before the service starts." "WARN"
}

if ($RunPreFlight) {
    Step-Progress "Running pre-flight check (runner --once)..." 38
    Log "Pre-flight: running runner --once..."
    if ($auth -and $auth.Var -eq "ANTHROPIC_AUTH_TOKEN") { $env:ANTHROPIC_AUTH_TOKEN = $auth.Value }
    if ($auth -and $auth.Var -eq "ANTHROPIC_API_KEY")    { $env:ANTHROPIC_API_KEY    = $auth.Value }
    & $Python $RunnerScript --once
    if ($LASTEXITCODE -ne 0) {
        Log "Runner --once exited $LASTEXITCODE. Check logs before installing service." "WARN"
    }
} else {
    Log "Pre-flight skipped (pass -RunPreFlight to opt in)."
}

# Create log dir
New-Item -ItemType Directory -Force $LogDir | Out-Null

# ---------------------------------------------------------------------------
# Resolve install method
# ---------------------------------------------------------------------------

$nssmPath = Find-NSSM
$isAdmin  = Is-Admin

if ($Method -eq "auto") {
    if ($nssmPath -and $isAdmin) {
        $Method = "nssm"
    } else {
        if ($nssmPath -and -not $isAdmin) {
            Log "NSSM found but not running as Administrator — falling back to Task Scheduler." "WARN"
            Log "Re-run as Administrator for NSSM installation." "WARN"
        } elseif (-not $nssmPath) {
            Log "NSSM not found — using Task Scheduler." "WARN"
            Log "Install NSSM for production installs: winget install NSSM.NSSM" "WARN"
        }
        $Method = "schtasks"
    }
}

Log "Install method: $Method"
Step-Progress "Installing agent service ($Method)..." 50

# ---------------------------------------------------------------------------
# Install via NSSM (requires Admin)
# ---------------------------------------------------------------------------

if ($Method -eq "nssm") {
    if (-not $isAdmin) {
        Log "NSSM installation requires Administrator. Re-run as Admin." "ERROR"
        exit 1
    }
    if (-not $nssmPath) {
        Log "NSSM not found. Install it: winget install NSSM.NSSM" "ERROR"
        exit 1
    }

    $nssmLog = "$LogDir\nssm-install.log"
    Log "Installing NSSM service '$ServiceName' (details: $nssmLog)..."
    & $nssmPath install     $ServiceName $Python                                              2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName AppParameters  $RunnerScript                        2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName AppDirectory   $ProjectRoot                         2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName DisplayName    $DisplayName                         2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName Description    $Description                         2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName Start          SERVICE_AUTO_START                   2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName AppRestartDelay 30000                               2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName AppStdout      "$LogDir\service-stdout.log"         2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName AppStderr      "$LogDir\service-stderr.log"         2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName AppStdoutCreationDisposition 4                      2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    & $nssmPath set         $ServiceName AppStderrCreationDisposition 4                      2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    $envExtra = "GIT_AUTHOR_NAME=Vault Bot GIT_AUTHOR_EMAIL=bot@localhost"
    if ($auth) { $envExtra += " $($auth.Var)=$($auth.Value)" }
    & $nssmPath set         $ServiceName AppEnvironmentExtra $envExtra                       2>&1 | Out-File $nssmLog -Append -Encoding UTF8

    Log "Starting service '$ServiceName'..."
    & $nssmPath start $ServiceName 2>&1 | Out-File $nssmLog -Append -Encoding UTF8
    Log "Service started."
}

# ---------------------------------------------------------------------------
# Install via Task Scheduler (no Admin required)
# ---------------------------------------------------------------------------

if ($Method -eq "schtasks") {
    # ONLOGON trigger requires admin — use HKCU Run key for auto-start at login.
    # No admin needed. Works for current user only.
    $RegPath  = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $RegValue = $TaskName   # reuse task name as registry value name
    $psCmd    = "pwsh.exe -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$DaemonScript`""

    # Remove existing run-key entry if present
    $existing = Get-ItemProperty $RegPath -Name $RegValue -ErrorAction SilentlyContinue
    if ($existing) {
        Log "Removing existing Run key '$RegValue'..."
        Remove-ItemProperty $RegPath -Name $RegValue -Force
    }

    # Register in HKCU Run — runs at every user login
    Set-ItemProperty $RegPath -Name $RegValue -Value $psCmd
    Log "Auto-start registered: HKCU\...\Run\$RegValue"
    Log "  Command: $psCmd"

    Log "Starting daemon..."
    $proc = Start-Process -FilePath "pwsh.exe" `
        -ArgumentList @("-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", $DaemonScript) `
        -WindowStyle Hidden -PassThru
    if ($proc) { Log "Daemon started (PID=$($proc.Id))." }
    else       { Log "Start-Process returned no handle — daemon may have launched detached." "WARN" }
}

# ---------------------------------------------------------------------------
# Default config + dashboard (built + served on $DashboardPort)
# ---------------------------------------------------------------------------

Step-Progress "Generating environment config..." 60
# Always produce the default settings file (ports come from global.json).
Write-DefaultConfig

if ($NoDashboard) {
    Log "Dashboard build/start skipped (-NoDashboard)."
} else {
    Setup-Dashboard -Method $Method
}

Step-Progress "Starting services..." 95

$masterLog = "$LogDir\automation.log"

Write-Progress -Activity "Nexus Campaigns Setup" -Completed

Log "=== Setup complete ==="
Log ""
if (-not $NoDashboard) { Log "Dashboard: http://localhost:$DashboardPort" }
Log "Monitor  : Get-Content '$masterLog' -Tail 50 -Wait"
Log "Status   : pwsh -File setup-service.ps1 -Status"
Log "Remove   : pwsh -File setup-service.ps1 -Uninstall"

if (-not (Assert-ServicesRunning -WaitForStartup)) {
    Log "Setup finished but validation detected failures. Check logs above." "ERROR"
    exit 1
}
exit 0
