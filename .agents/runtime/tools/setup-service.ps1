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

param(
    [string] $ProjectRoot    = "C:\opt\GitHub\NexusCampaigns",
    [string] $Python         = "python",
    [string] $Method         = "auto",    # "auto" | "nssm" | "schtasks"
    [int]    $DashboardPort  = 48080,      # Next.js dashboard port (default from config; overrides config when passed)
    [switch] $NoDashboard,                 # skip dashboard install/start
    [switch] $Force,                       # overwrite generated default config (.env.local)
    [switch] $Uninstall,
    [switch] $Status,
    [switch] $RunPreFlight            # opt-in: run runner --once before installing (slow, ~60s)
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

exit 0
