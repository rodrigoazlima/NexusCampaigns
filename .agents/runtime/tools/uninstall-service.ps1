#Requires -RunAsAdministrator
# Removes vault-knowledge-factory Windows service (NSSM or Task Scheduler).
# Vault content and state files are NOT removed — delete manually if desired.
# Run once from an elevated PowerShell prompt.

param(
    [ValidateSet("nssm", "scheduler")]
    [string]$Method = "nssm"
)

$SvcName  = "vault-knowledge-factory"
$TaskName = "VaultKnowledgeFactory"

switch ($Method) {
    "nssm" {
        Write-Host "Stopping service '$SvcName'..."
        nssm stop $SvcName
        Write-Host "Removing service '$SvcName'..."
        nssm remove $SvcName confirm
        Write-Host "Done."
    }
    "scheduler" {
        Write-Host "Deleting task '$TaskName'..."
        schtasks /delete /tn $TaskName /f
        Write-Host "Done."
    }
}
