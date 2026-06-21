#Requires -Version 5.1
# Test-ClassifyImages.ps1 - Unit tests for 06-classify-images LLM classification
# Run: powershell -ExecutionPolicy Bypass -File .automation\tests\Test-ClassifyImages.ps1
# Exit code 0 = all pass, 1 = one or more failures

$VaultRoot   = 'C:\opt\GitHub\NexusCampaigns\knowledge-base'
$LMStudioUrl = 'http://localhost:1234/v1/chat/completions'
$Model       = 'qwen3-vl-4b-instruct'
$MaxRetries  = 3

$ValidTypes        = @('portrait','body','battlemap','scene')
$ValidRaces        = @('human','elf','dark-elf','dwarf','orc','goblin','troll','ogre','dragon','angel','devil','demon','undead','skeleton','zombie','vampire','werewolf','spirit')
$ValidClasses      = @('warrior','mage','archer','cleric','paladin','necromancer','assassin','monster','none')
$ValidElements     = @('fire','water','earth','air','nature','dark','light','none')
$ValidEnvironments = @('dungeon','cave','forest','city','tavern','desert','snow','sea','swamp','ruins','temple','castle','plains','mountain','interior','exterior','none')

$Prompt = @'
Return JSON only. No explanation, no markdown fences.

First decide the image type:
- "battlemap": top-down tactical map (grid map, overhead view of terrain/rooms/dungeon/exterior)
- "portrait": close-up face or bust shot of a character or creature (head and shoulders only)
- "body": full-body illustration of a character or creature (whole figure visible)
- "scene": static background, environment art, or scenery illustration with no primary character subject (perspective view of a location, landscape, interior, or atmospheric setting)

Schema:
{
  "type": "",
  "race": "",
  "class": "",
  "element": "",
  "environment": ""
}

Rules:
- type: portrait, body, battlemap, or scene (required)
- race/class/element: fill for portrait and body; use "none" for battlemap and scene
- environment: fill for battlemap and scene (the terrain/setting shown); use "none" for portrait and body

Allowed type: portrait, body, battlemap, scene
Allowed race: human, elf, dark-elf, dwarf, orc, goblin, troll, ogre, dragon, angel, devil, demon, undead, skeleton, zombie, vampire, werewolf, spirit
Allowed class: warrior, mage, archer, cleric, paladin, necromancer, assassin, monster, none
Allowed element: fire, water, earth, air, nature, dark, light, none
Allowed environment: dungeon, cave, forest, city, tavern, desert, snow, sea, swamp, ruins, temple, castle, plains, mountain, interior, exterior, none

Reply with ONLY the JSON object.
'@

function Get-MimeType {
    param([string]$Ext)
    switch ($Ext.ToLower()) {
        '.jpg'  { return 'image/jpeg' }
        '.jpeg' { return 'image/jpeg' }
        '.webp' { return 'image/webp' }
        default { return 'image/png' }
    }
}

function Invoke-VisionLLM {
    param([string]$ImagePath)
    $bytes   = [System.IO.File]::ReadAllBytes($ImagePath)
    $b64     = [Convert]::ToBase64String($bytes)
    $mime    = Get-MimeType -Ext ([System.IO.Path]::GetExtension($ImagePath))
    $dataUrl = "data:${mime};base64,${b64}"

    $body = [ordered]@{
        model       = $Model
        temperature = 0
        max_tokens  = 120
        messages    = @(
            @{
                role    = 'user'
                content = @(
                    @{ type = 'text'; text = $Prompt }
                    @{ type = 'image_url'; image_url = @{ url = $dataUrl } }
                )
            }
        )
    } | ConvertTo-Json -Depth 10

    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        try {
            $resp = Invoke-RestMethod `
                -Uri         $LMStudioUrl `
                -Method      POST `
                -ContentType 'application/json' `
                -Body        $body `
                -TimeoutSec  120

            $raw = $resp.choices[0].message.content.Trim()
            $raw = $raw -replace '(?s)```[a-z]*\s*', '' -replace '```', ''

            if ($raw -match '(?s)(\{.+?\})') {
                $obj  = $Matches[1] | ConvertFrom-Json
                $type = if ($ValidTypes        -contains $obj.type)                                    { $obj.type }        else { 'portrait' }
                $race = if ($obj.race    -eq 'none' -or ($ValidRaces    -contains $obj.race))          { $obj.race }        else { 'unknown' }
                $cls  = if ($obj.class   -eq 'none' -or ($ValidClasses  -contains $obj.class))         { $obj.class }       else { 'none' }
                $elem = if ($obj.element -eq 'none' -or ($ValidElements -contains $obj.element))       { $obj.element }     else { 'none' }
                $env  = if ($ValidEnvironments -contains $obj.environment)                             { $obj.environment } else { 'none' }
                if ($type -eq 'battlemap' -or $type -eq 'scene') {
                    $race = 'none'; $cls = 'none'; $elem = 'none'
                }
                return [ordered]@{
                    Type        = $type
                    Race        = $race
                    Class       = $cls
                    Element     = $elem
                    Environment = $env
                    RawResponse = $raw
                }
            }
            Write-Host "  [attempt $attempt] unexpected: $raw"
        } catch {
            Write-Host "  [attempt $attempt] error: $_"
        }
        if ($attempt -lt $MaxRetries) { Start-Sleep -Seconds 3 }
    }
    return $null
}

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

$results = @{ Passed = 0; Failed = 0 }

function Pass { param([string]$msg) Write-Host "  PASS  $msg" -ForegroundColor Green;  $results.Passed++ }
function Fail { param([string]$msg) Write-Host "  FAIL  $msg" -ForegroundColor Red;    $results.Failed++ }
function Skip { param([string]$msg) Write-Host "  SKIP  $msg" -ForegroundColor Yellow }

function Assert-Eq {
    param([string]$label, $got, $expected)
    if ($got -eq $expected) { Pass "$label  (got: $got)" }
    else                    { Fail "$label  expected='$expected'  got='$got'" }
}

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

Write-Host "`n=== Test-ClassifyImages ==="

# --- TC-01: 86d2ffdf13ae5a06262e0380cbfd0c8d.jpg must be battlemap ---
Write-Host "`n[TC-01] battlemap detection: 86d2ffdf13ae5a06262e0380cbfd0c8d.jpg"
$imgPath = "$VaultRoot\00-Inbox\exmaple-battlemap-ice.jpg"
if (-not (Test-Path $imgPath)) {
    Skip "file not found: $imgPath"
} else {
    Write-Host "  Calling VLM..." -NoNewline
    $meta = Invoke-VisionLLM -ImagePath $imgPath
    Write-Host " done."
    Write-Host "  Raw: $($meta.RawResponse)"

    if ($null -eq $meta) {
        Fail "LLM returned null after $MaxRetries attempts"
    } else {
        Assert-Eq "type"    $meta.Type    "battlemap"
        Assert-Eq "race"    $meta.Race    "none"
        Assert-Eq "class"   $meta.Class   "none"
        Assert-Eq "element" $meta.Element "none"
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

$total = $results.Passed + $results.Failed
Write-Host "`n=== Results: $($results.Passed)/$total passed ==="
if ($results.Failed -gt 0) {
    Write-Host "FAILED" -ForegroundColor Red
    exit 1
} else {
    Write-Host "ALL PASSED" -ForegroundColor Green
    exit 0
}
