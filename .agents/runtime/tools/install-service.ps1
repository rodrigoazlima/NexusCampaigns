#Requires -RunAsAdministrator
# Installs vault-knowledge-factory as a Windows service via NSSM.
# Run once from an elevated PowerShell prompt.
#
# Prerequisites:
#   1. nssm.exe on PATH  (https://nssm.cc/download)
#   2. pip install -r requirements.txt
#   3. Set API key params below or export them as environment variables before running

param(
    [string]$ProjectRoot      = "C:\opt\GitHub\NexusCampaigns",
    [string]$Python           = "python",
    [string]$ApiKey           = $env:ANTHROPIC_API_KEY,
    [string]$OpenAIKey        = $(if ($env:OPENAI_API_KEY) { $env:OPENAI_API_KEY } else { "lm-studio" }),
    [string]$GeminiKey        = $env:GEMINI_API_KEY,
    [string]$OpenRouterKey    = $env:OPENROUTER_API_KEY
)

$SvcName = "vault-knowledge-factory"
$Runner  = "$ProjectRoot\.agents\runtime\tools\runner.py"
$LogsDir = "$ProjectRoot\.agents\runtime\state\logs"

New-Item -ItemType Directory -Force $LogsDir | Out-Null

# Verify runner starts cleanly before registering
Write-Host "Verifying runner (--once)..."
& $Python $Runner --once
if ($LASTEXITCODE -ne 0) {
    Write-Error "Runner exited with code $LASTEXITCODE. Fix before installing service."
    exit 1
}

nssm install $SvcName $Python
nssm set $SvcName AppParameters "`"$Runner`""
nssm set $SvcName AppDirectory $ProjectRoot
nssm set $SvcName DisplayName "Vault Nexus Campaigns"
nssm set $SvcName Description "DM pipeline - ingests, classifies, and links vault entities on schedule"
nssm set $SvcName Start SERVICE_AUTO_START
nssm set $SvcName AppRestartDelay 30000
nssm set $SvcName AppStdout "$LogsDir\service-stdout.log"
nssm set $SvcName AppStderr "$LogsDir\service-stderr.log"

$envBlock = [System.Collections.Generic.List[string]]@(
    "GIT_AUTHOR_NAME=Vault Bot",
    "GIT_AUTHOR_EMAIL=bot@localhost",
    "ANTHROPIC_API_KEY=$ApiKey",
    "OPENAI_API_KEY=$OpenAIKey"
)
if ($GeminiKey)     { $envBlock.Add("GEMINI_API_KEY=$GeminiKey") }
if ($OpenRouterKey) { $envBlock.Add("OPENROUTER_API_KEY=$OpenRouterKey") }
nssm set $SvcName AppEnvironmentExtra ($envBlock -join "`n")

nssm start $SvcName

Write-Host "Service '$SvcName' installed and started."
Write-Host "Status : nssm status $SvcName"
Write-Host "Logs   : $LogsDir\automation.log"
