# setup-service.ps1 — One-command install for Nexus Campaigns
#
# Installs EVERYTHING: pip deps, the agent pipeline service, and the Next.js
# dashboard (built + served on port 48080). Run once from an elevated shell.
#
# Supported methods (auto-detected):
#   nssm      — NSSM service manager (requires Admin; recommended for production)
#   schtasks  — Windows Task Scheduler / HKCU Run (works without Admin; starts at logon)
#
# Usage (requires pwsh / PowerShell 7+):
#   # One command, install it all (run as Administrator):
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
#   # Skip runner --once pre-flight (use when already verified):
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -SkipPreFlight
#
#   # Uninstall (removes both services):
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Uninstall
#
#   # Check status:
#   pwsh -ExecutionPolicy Bypass -File setup-service.ps1 -Status

param(
    [string] $ProjectRoot    = "C:\opt\GitHub\NexusCampaigns",
    [string] $Python         = "python",
    [string] $Method         = "auto",    # "auto" | "nssm" | "schtasks"
    [int]    $DashboardPort  = 48080,      # Next.js dashboard port (default from config; overrides config when passed)
    [switch] $NoDashboard,                 # skip dashboard install/start
    [switch] $Force,                       # overwrite generated default config (.env.local)
    [switch] $Uninstall,
    [switch] $Status,
    [switch] $SkipPreFlight           # skip runner --once verification (use after first successful run)
)

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

# Produce a default settings file for the dashboard, derived from the codebase
# config (global.json) + this install's project root. Ports come from config.
# Does not clobber an existing file unless -Force is given.
function Write-DefaultConfig {
    $envFile = "$DashboardDir\.env.local"

    if (-not (Test-Path $DashboardDir)) {
        Log "Dashboard dir not found: $DashboardDir — skipping config generation." "WARN"
        return
    }
    if ((Test-Path $envFile) -and -not $Force) {
        Log "Default config already exists: $envFile (use -Force to regenerate). Keeping it."
        return
    }

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $lines = @(
        "# Generated by setup-service.ps1 on $stamp",
        "# Default dashboard settings derived from .system/.shared/config/global.json.",
        "# Change the port in global.json (ports.dashboard) and re-run setup -Force, or edit here.",
        "PROJECT_ROOT=$ProjectRoot",
        "VAULT_ROOT=$VaultRootAbs",
        "PORT=$DashboardPort",
        "HOSTNAME=$DashboardHost"
    )
    Set-Content -Path $envFile -Value $lines -Encoding UTF8
    Log "Produced default config: $envFile"
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

    # Install deps + production build
    Push-Location $DashboardDir
    try {
        Log "Installing dashboard dependencies (npm install)..."
        & $npm install
        if ($LASTEXITCODE -ne 0) { Log "npm install failed — skipping dashboard." "ERROR"; return }
        Log "Building dashboard (npm run build)..."
        & $npm run build
        if ($LASTEXITCODE -ne 0) { Log "npm run build failed — skipping dashboard." "ERROR"; return }
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
        Log "Installing NSSM service '$DashboardSvc'..."
        & $nssmPath install $DashboardSvc $nodePath
        & $nssmPath set     $DashboardSvc AppParameters  "`"$nextBin`" start --port $DashboardPort --hostname $DashboardHost"
        & $nssmPath set     $DashboardSvc AppDirectory   $DashboardDir
        & $nssmPath set     $DashboardSvc DisplayName    "Vault Nexus Dashboard"
        & $nssmPath set     $DashboardSvc Description    "Nexus Campaigns admin dashboard (Next.js) on port $DashboardPort"
        & $nssmPath set     $DashboardSvc Start          SERVICE_AUTO_START
        & $nssmPath set     $DashboardSvc AppRestartDelay 30000
        & $nssmPath set     $DashboardSvc AppStdout      "$LogDir\dashboard-stdout.log"
        & $nssmPath set     $DashboardSvc AppStderr      "$LogDir\dashboard-stderr.log"
        & $nssmPath set     $DashboardSvc AppStdoutCreationDisposition 4
        & $nssmPath set     $DashboardSvc AppStderrCreationDisposition 4
        & $nssmPath set     $DashboardSvc AppEnvironmentExtra "NODE_ENV=production PORT=$DashboardPort HOSTNAME=$DashboardHost"
        & $nssmPath start   $DashboardSvc
        Log "Dashboard service installed and started -> http://localhost:$DashboardPort"
    } else {
        # No admin: auto-start at logon via HKCU Run, plus start now (detached, hidden).
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
# Status
# ---------------------------------------------------------------------------

if ($Status) {
    Log "Checking service status..."

    # NSSM service
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        Log "NSSM service '$ServiceName': $($svc.Status)"
    } else {
        Log "NSSM service '$ServiceName': not installed"
    }

    # HKCU Run key (schtasks method)
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $runVal  = Get-ItemProperty $regPath -Name $TaskName -ErrorAction SilentlyContinue
    if ($runVal) {
        Log "HKCU Run key '$TaskName': registered"
        Log "  -> $($runVal.$TaskName)"
    } else {
        Log "HKCU Run key '$TaskName': not registered"
    }

    # Runner process
    $procs = Get-Process python -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -like "*runner.py*" }
    if ($procs) {
        Log "Runner processes: $($procs.Count) running (PIDs: $($procs.Id -join ', '))"
    } else {
        Log "Runner process: not detected"
    }

    # Lock file
    $lockFile = "$ProjectRoot\.agents\runtime\state\runner.lock"
    if (Test-Path $lockFile) {
        $lockData = Get-Content $lockFile -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
        Log "Lock file: present (PID=$($lockData.pid) since $($lockData.startedAt))"
    } else {
        Log "Lock file: absent (runner not currently executing a cycle)"
    }

    # Dashboard
    $dsvc = Get-Service -Name $DashboardSvc -ErrorAction SilentlyContinue
    if ($dsvc) {
        Log "Dashboard service '$DashboardSvc': $($dsvc.Status)"
    } else {
        Log "Dashboard service '$DashboardSvc': not installed"
    }
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $dRun = Get-ItemProperty $regPath -Name $DashboardRun -ErrorAction SilentlyContinue
    if ($dRun) { Log "Dashboard Run key '$DashboardRun': registered" }
    $dPort = Get-NetTCPConnection -State Listen -LocalPort $DashboardPort -ErrorAction SilentlyContinue
    if ($dPort) { Log "Dashboard: listening on port $DashboardPort -> http://localhost:$DashboardPort" }
    else        { Log "Dashboard: port $DashboardPort not listening" }

    # Config
    Log "Configured port (global.json ports.dashboard): $DashboardPort"
    $envFile = "$DashboardDir\.env.local"
    if (Test-Path $envFile) { Log "Default config: $envFile (present)" }
    else                    { Log "Default config: $envFile (not generated yet)" }

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
# Pre-flight checks
# ---------------------------------------------------------------------------

Log "=== Vault Nexus Campaigns — Service Setup ==="
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

# Install pip dependencies
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

# Verify one-shot run
if ($SkipPreFlight) {
    Log "Pre-flight skipped (-SkipPreFlight)."
} else {
    Log "Verifying runner --once..."
    if ($auth -and $auth.Var -eq "ANTHROPIC_AUTH_TOKEN") { $env:ANTHROPIC_AUTH_TOKEN = $auth.Value }
    if ($auth -and $auth.Var -eq "ANTHROPIC_API_KEY")    { $env:ANTHROPIC_API_KEY    = $auth.Value }
    & $Python $RunnerScript --once
    if ($LASTEXITCODE -ne 0) {
        Log "Runner --once exited $LASTEXITCODE. Check logs before installing service." "WARN"
    }
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

    # Remove existing service if present
    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existing) {
        Log "Removing existing NSSM service '$ServiceName'..."
        if ($existing.Status -eq "Running") { & $nssmPath stop $ServiceName }
        & $nssmPath remove $ServiceName confirm
    }

    Log "Installing NSSM service '$ServiceName'..."
    & $nssmPath install     $ServiceName $Python
    & $nssmPath set         $ServiceName AppParameters  $RunnerScript
    & $nssmPath set         $ServiceName AppDirectory   $ProjectRoot
    & $nssmPath set         $ServiceName DisplayName    $DisplayName
    & $nssmPath set         $ServiceName Description    $Description
    & $nssmPath set         $ServiceName Start          SERVICE_AUTO_START
    & $nssmPath set         $ServiceName AppRestartDelay 30000
    & $nssmPath set         $ServiceName AppStdout      "$LogDir\service-stdout.log"
    & $nssmPath set         $ServiceName AppStderr      "$LogDir\service-stderr.log"
    & $nssmPath set         $ServiceName AppStdoutCreationDisposition 4
    & $nssmPath set         $ServiceName AppStderrCreationDisposition 4

    # Environment variables
    $envExtra = "GIT_AUTHOR_NAME=Vault Bot GIT_AUTHOR_EMAIL=bot@localhost"
    if ($auth) { $envExtra += " $($auth.Var)=$($auth.Value)" }
    & $nssmPath set $ServiceName AppEnvironmentExtra $envExtra

    Log "Starting service..."
    & $nssmPath start $ServiceName
    Log "NSSM service installed and started."
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

    # Start daemon immediately in a detached background process (no window)
    Log "Starting daemon now..."
    $startArgs = @{
        FilePath     = "pwsh.exe"
        ArgumentList = @("-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", $DaemonScript)
        WindowStyle  = "Hidden"
        PassThru     = $true
    }
    $proc = Start-Process @startArgs
    if ($proc) {
        Log "Daemon started (PID=$($proc.Id))."
    } else {
        Log "Start-Process returned no handle — daemon may have launched detached." "WARN"
    }
}

# ---------------------------------------------------------------------------
# Default config + dashboard (built + served on $DashboardPort)
# ---------------------------------------------------------------------------

# Always produce the default settings file (ports come from global.json).
Write-DefaultConfig

if ($NoDashboard) {
    Log "Dashboard build/start skipped (-NoDashboard)."
} else {
    Setup-Dashboard -Method $Method
}

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

Log "Waiting 5 seconds for service to initialise..."
Start-Sleep -Seconds 5

# Check lock file
$lockFile = "$ProjectRoot\.agents\runtime\state\runner.lock"
if (Test-Path $lockFile) {
    Log "Lock file present — runner is active."
} else {
    Log "Lock file not found — runner may not have started yet (normal on first cycle)." "WARN"
}

# Show last 10 lines of automation log
$masterLog = "$LogDir\automation.log"
if (Test-Path $masterLog) {
    Log "Last log entries:"
    Get-Content $masterLog -Tail 10 | ForEach-Object { Write-Host "  $_" }
}

Log "=== Setup complete ==="
Log ""
if (-not $NoDashboard) { Log "Dashboard: http://localhost:$DashboardPort" }
Log "Monitor  : Get-Content '$masterLog' -Tail 50 -Wait"
Log "Status   : powershell -File setup-service.ps1 -Status"
Log "Remove   : powershell -File setup-service.ps1 -Uninstall"
