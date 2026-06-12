# Vault Knowledge Factory daemon — calls runner.py every $IntervalSec seconds.
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
    [string]$ProjectRoot = "C:\opt\GitHub\NexusCampaigns",
    [string]$Python      = "python",
    [int]   $IntervalSec = 60
)

$Runner = "$ProjectRoot\.agents\runtime\tools\runner.py"

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

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: --- STARTING daemon (interval=${IntervalSec}s) ---"
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: ProjectRoot=$ProjectRoot"
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [daemon] INFO: Python=$Python"

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
