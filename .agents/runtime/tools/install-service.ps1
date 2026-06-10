#Requires -RunAsAdministrator
# Installs VaultKnowledgeFactory as a Windows service via NSSM.
# Run once from an elevated PowerShell prompt.

$ProjectRoot = "C:\opt\GitHub\NexusCampaigns"
$VaultRoot   = "C:\opt\GitHub\NexusCampaigns\knowledge-base"
$Python      = "C:\opt\Python\Python310\python.exe"
$Runner      = "$ProjectRoot\.agents\orchestrator\tools\runner.py"
$LogsDir     = "$ProjectRoot\.agents\orchestrator\state\logs"
$SvcName     = "vault-knowledge-factory"

New-Item -ItemType Directory -Force $LogsDir | Out-Null

nssm install $SvcName $Python
nssm set $SvcName AppParameters "`"$Runner`""
nssm set $SvcName AppDirectory $ProjectRoot
nssm set $SvcName DisplayName "Vault Knowledge Factory"
nssm set $SvcName Description "DM pipeline - ingests, classifies, and links vault entities on schedule"
nssm set $SvcName Start SERVICE_AUTO_START
nssm set $SvcName AppRestartDelay 30000
nssm set $SvcName AppStdout "$LogsDir\service-stdout.log"
nssm set $SvcName AppStderr "$LogsDir\service-stderr.log"
nssm set $SvcName AppEnvironmentExtra `
    "VAULT_ROOT=$VaultRoot" `
    "LLM_TEXT_URL=http://localhost:11434" `
    "LLM_VISION_URL=http://localhost:11435" `
    "LLM_TEXT_MODEL=mistral:7b" `
    "LLM_VISION_MODEL=llava:13b" `
    "GIT_AUTHOR_NAME=Vault Bot" `
    "GIT_AUTHOR_EMAIL=bot@localhost"

nssm start $SvcName
Write-Host "Service '$SvcName' installed and started."
Write-Host "Check status: nssm status $SvcName"
Write-Host "Logs: $LogsDir\automation.log"
