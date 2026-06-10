$env:VAULT_ROOT = "C:\opt\GitHub\NexusCampaigns\knowledge-base"
$env:LLM_TEXT_URL = "http://localhost:11434"
$env:LLM_VISION_URL = "http://localhost:11435"
$env:LLM_TEXT_MODEL = "mistral:7b"
$env:LLM_VISION_MODEL = "llava:13b"
$env:GIT_AUTHOR_NAME = "Vault Bot"
$env:GIT_AUTHOR_EMAIL = "bot@localhost"

while ($true) {
    & "C:\opt\Python\Python310\python.exe" "C:\opt\GitHub\NexusCampaigns\.agents\orchestrator\tools\runner.py" --once
    Start-Sleep -Seconds 60
}
