# Vault Nexus Campaigns daemon — calls runner.py every $IntervalSec seconds.
#
# Auth strategy (priority order):
#   1. ANTHROPIC_API_KEY already in environment (permanent API key — preferred)
#   2. ANTHROPIC_AUTH_TOKEN already in environment (OAuth token set externally)
#   3. Auto-load OAuth token from %USERPROFILE%\.claude\.credentials.json
#
# Usage:
#   powershell -NonInteractive -WindowStyle Hidden -File daemon.ps1
#   powershell -NonInteractive -File daemon.ps1 -ProjectRoot C:\path\to\repo

param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path,
    [string]$Python      = "python",
    [int]   $IntervalSec = 60
)

$Runner = "$ProjectRoot\agents\runtime\tools\runner.py"

# ---------------------------------------------------------------------------
# Auth bootstrap — set ANTHROPIC_AUTH_TOKEN from Claude credentials if needed
# ---------------------------------------------------------------------------
function Load-AnthropicAuth {
    if ($env:ANTHROPIC_API_KEY) { return }   # permanent key takes priority
    if ($env:ANTHROPIC_AUTH_TOKEN) { return } # already set externally

    $credsFile = "$env:USERPROFILE\.claude\.credentials.json"
    if (-not (Test-Path $credsFile)) { return }

    try {
        $creds = Get-Content $credsFile -Raw | ConvertFrom-Json
        $token = $creds.claudeAiOauth.accessToken
        $expiresAt = $creds.claudeAiOauth.expiresAt  # milliseconds epoch

        if (-not $token) { return }

        # Check if token is still valid (with 5-minute buffer)
        $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        if ($expiresAt -and ($nowMs -gt ($expiresAt - 300000))) {
            Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: OAuth token expired or expiring soon — set ANTHROPIC_API_KEY for uninterrupted service"
            return
        }

        $env:ANTHROPIC_AUTH_TOKEN = $token
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: Loaded OAuth token from credentials (expires $(([DateTimeOffset]::FromUnixTimeMilliseconds($expiresAt)).ToString('yyyy-MM-dd HH:mm:ss zzz')))"
    } catch {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: Could not load credentials: $_"
    }
}

# ---------------------------------------------------------------------------
# Set Git identity if not already configured
# ---------------------------------------------------------------------------
if (-not $env:GIT_AUTHOR_NAME)  { $env:GIT_AUTHOR_NAME  = "Vault Bot" }
if (-not $env:GIT_AUTHOR_EMAIL) { $env:GIT_AUTHOR_EMAIL = "bot@localhost" }

# ---------------------------------------------------------------------------
# Startup git sync — fetch + pull ProjectRoot before starting the loop.
# 3 attempts, 30s apart; if all fail, log a warning and start anyway.
# ---------------------------------------------------------------------------
# Runs a git command with a hard timeout. A hung network op (fetch/pull) would
# otherwise block the daemon forever and leave .git/index.lock behind for every
# other git user of the repo. On timeout, kill the process tree so the lock
# is released cleanly instead of left dangling for someone else to clear.
function Invoke-GitWithTimeout {
    param([string]$RepoPath, [string[]]$GitArgs, [int]$TimeoutSec = 60)

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "git"
    $psi.Arguments = ($GitArgs -join ' ')
    $psi.WorkingDirectory = $RepoPath
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute = $false

    $proc = [System.Diagnostics.Process]::Start($psi)
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: git $($GitArgs -join ' ') timed out after ${TimeoutSec}s — killing process"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $lockFile = Join-Path $RepoPath ".git\index.lock"
        if (Test-Path $lockFile) {
            Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
            Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: removed stale $lockFile after kill"
        }
        return 1
    }
    Write-Host ($proc.StandardOutput.ReadToEnd())
    $errOut = $proc.StandardError.ReadToEnd()
    if ($errOut) { Write-Host $errOut }
    return $proc.ExitCode
}

function Sync-ProjectRepo {
    param([string]$RepoPath, [int]$MaxAttempts = 3, [int]$RetryDelaySec = 30, [int]$GitTimeoutSec = 60)

    # A leftover index.lock with no owning git process is stale (e.g. daemon was
    # killed mid-fetch) — clear it before attempting sync so we don't fail on
    # someone else's crash instead of our own.
    $lockFile = Join-Path $RepoPath ".git\index.lock"
    if (Test-Path $lockFile) {
        $gitProcs = Get-Process git -ErrorAction SilentlyContinue
        if (-not $gitProcs) {
            Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: stale $lockFile found with no running git process — removing"
            Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
        }
    }

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: git sync attempt $attempt/$MaxAttempts ($RepoPath)"
        try {
            $fetchExit = Invoke-GitWithTimeout -RepoPath $RepoPath -GitArgs @("fetch") -TimeoutSec $GitTimeoutSec
            if ($fetchExit -ne 0) { throw "git fetch exited $fetchExit" }
            $pullExit = Invoke-GitWithTimeout -RepoPath $RepoPath -GitArgs @("pull") -TimeoutSec $GitTimeoutSec
            if ($pullExit -ne 0) { throw "git pull exited $pullExit" }
            Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: git sync OK"
            return $true
        } catch {
            Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: git sync attempt $attempt failed: $_"
        }
        if ($attempt -lt $MaxAttempts) { Start-Sleep -Seconds $RetryDelaySec }
    }

    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: git sync failed after $MaxAttempts attempts — starting service without update."
    return $false
}

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: --- STARTING daemon (interval=${IntervalSec}s) ---"
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: ProjectRoot=$ProjectRoot"
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: Python=$Python"

Sync-ProjectRepo -RepoPath $ProjectRoot | Out-Null

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
while ($true) {
    # Re-load auth on every iteration so token refresh is picked up automatically
    Load-AnthropicAuth

    & $Python $Runner --once

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] WARN: runner exited with code $exitCode"
    }

    Start-Sleep -Seconds $IntervalSec
}
