# =============================================
# generate-prompts-for-config-py.ps1
# =============================================

param(
    [string]$TemplateFile = "prompt-template-config-py.md",
    [string]$AgentsRoot   = (Join-Path $PSScriptRoot "..\..\.agents"),
    [string]$OutputDir    = ".",
    [string]$OutputPrefix = "prompt-config-py",
    [switch]$SkipEmpty
)

if (-not (Test-Path $TemplateFile)) {
    Write-Error "Template file '$TemplateFile' not found."
    exit 1
}

$template = Get-Content -Path $TemplateFile -Raw

$pyFiles = Get-ChildItem -Path $AgentsRoot -Recurse -Filter "*.py" |
    Where-Object { -not $SkipEmpty -or $_.Length -gt 0 } |
    Where-Object { $_.Name -ne "__init__.py" }

if ($pyFiles.Count -eq 0) {
    Write-Warning "No Python files found under '$AgentsRoot'."
    exit 0
}

$generated = 0

foreach ($file in $pyFiles) {
    $scriptContent = Get-Content -Path $file.FullName -Raw -Encoding UTF8

    # Build a readable relative path for context
    $relativePath = $file.FullName -replace [regex]::Escape((Resolve-Path $AgentsRoot).Path + "\"), ""

    $content = $template -replace [regex]::Escape("{python-script}"), "# $relativePath`n$scriptContent"

    $slug    = $file.BaseName
    $outFile = Join-Path $OutputDir "${OutputPrefix}-${slug}.md"

    $content | Out-File -FilePath $outFile -Encoding UTF8 -Force

    Write-Host "Created: $outFile  <-  $relativePath" -ForegroundColor Green
    $generated++
}

Write-Host "`nDone. Generated $generated prompt files." -ForegroundColor Cyan
