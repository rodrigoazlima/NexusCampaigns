# =============================================
# generate-prompts.ps1
# =============================================

param(
    [string]$TemplateFile = "template.md",
    [string]$OutputPrefix = "prompt"
)

# List of spec files
$specFiles = @(
    "agent-classification.spec.md",
    "agent-cleanup.spec.md",
    "agent-dispatch.spec.md",
    "agent-ingestion.spec.md",
    "agent-lore.spec.md",
    "agent-registry.spec.md",
    "agent-repair.spec.md",
    "agent-review.spec.md",
    "agent-token.spec.md",
    "agent-vision.spec.md",
    "agent-wiki.spec.md",
    "agent-wikilink.spec.md",
    "automation-system.spec.md",
    "data-contracts.spec.md",
    "linking-rules.spec.md",
    "llm-integration.spec.md",
    "security.spec.md",
    "service-install.spec.md",
    "shared-library.spec.md",
    "state-files.spec.md"
)

# Read the template
if (-not (Test-Path $TemplateFile)) {
    Write-Error "Template file '$TemplateFile' not found in the current folder!"
    Write-Host "Please create a file named 'template.md' with {spec_file_or_name} in it." -ForegroundColor Yellow
    exit 1
}

$template = Get-Content -Path $TemplateFile -Raw

# Generate the prompt files
for ($i = 1; $i -le $specFiles.Count; $i++) {
    $specName = $specFiles[$i-1]
    $outputFile = "${OutputPrefix}-${i}.md"
    
    $content = $template -replace [regex]::Escape("{spec_file_or_name}"), $specName
    
    $content | Out-File -FilePath $outputFile -Encoding UTF8 -Force
    
    Write-Host "✅ Created: $outputFile  ←  $specName" -ForegroundColor Green
}

Write-Host "`n🎉 Done! Generated $($specFiles.Count) prompt files." -ForegroundColor Cyan