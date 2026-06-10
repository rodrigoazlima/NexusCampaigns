# Claude Prompt Runner Script
# Runs claude --dangerously-skip-permissions -p with each prompt from docs/prompts/
# Handles failures, timeout, and credit errors with retry logic

param(
    [string]$PromptDirectory = "docs/prompts",
    [string]$StateFile = ".system/claude-queue-state.json",
    [int]$RetryDelayMinutes = 40,
    [int]$MaxRetries = 200,
    [int]$TimeoutMinutes = 10
)

$TimeoutSeconds = $TimeoutMinutes * 60
$RetryDelaySeconds = $RetryDelayMinutes * 60

$FailurePatterns = @(
    "usage limit reached",
    "insufficient credits",
    "credit limit reached"
)

function Get-Prompts {
    param([string]$Directory)

    if (-not (Test-Path $Directory)) {
        Write-Host "Error: Prompt directory '$Directory' not found." -ForegroundColor Red
        return @()
    }

    $promptFiles = Get-ChildItem -Path "$Directory/prompt-*.md" -File | Sort-Object Name
    return $promptFiles.FullName
}

function Load-State {
    param([string]$StateFilePath)

    if (Test-Path $StateFilePath) {
        Write-Host "Loading existing queue state from '$StateFilePath'..."
        try {
            $content = Get-Content $StateFilePath -Raw -Encoding UTF8 | ConvertFrom-Json
            return $content.prompts
        }
        catch {
            Write-Host "Warning: Failed to load state file, starting fresh." -ForegroundColor Yellow
            return @()
        }
    }
    return @()
}

function Save-State {
    param([string]$StateFilePath, [array]$Prompts)

    $dir = Split-Path $StateFilePath -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    @{ prompts = $Prompts } | ConvertTo-Json -Depth 10 | Set-Content $StateFilePath -Encoding UTF8
}

function Format-PromptName {
    param([string]$Path)
    return Split-Path $Path -Leaf
}

function Test-Failure {
    param([string]$Output, [int]$ExitCode)

    if ($ExitCode -ne 0) { return $true }

    foreach ($pattern in $FailurePatterns) {
        if ($Output -match [regex]::Escape($pattern)) { return $true }
    }

    return $false
}

function Get-TimeElapsed {
    param([datetime]$StartTime)
    return [math]::Floor(((Get-Date) - $StartTime).TotalSeconds)
}

function Write-Status {
    param([string]$Message, [ConsoleColor]$Color = "White")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$timestamp] $Message" -ForegroundColor $Color
}

# Main execution
Write-Status "Claude Prompt Runner Starting" -Color Green
Write-Status "Prompt directory: $PromptDirectory" -Color Gray
Write-Status "State file: $StateFile" -Color Gray
Write-Status "Retry delay: $RetryDelayMinutes minutes" -Color Gray
Write-Status "Max retries: $MaxRetries" -Color Gray

$existingState = Load-State $StateFile

if ($existingState.Count -eq 0) {
    Write-Status "Discovering prompt files..."
    $promptPaths = Get-Prompts $PromptDirectory

    if ($promptPaths.Count -eq 0) {
        Write-Status "No prompt files found!" -Color Yellow
        exit 0
    }

    $queueState = @()
    foreach ($path in $promptPaths) {
        $queueState += [PSCustomObject]@{
            Path      = $path
            Retries   = 0
            LastRun   = $null
            Completed = $false
        }
    }
}
else {
    Write-Status "Continuing with existing queue..."
    $queueState = $existingState
}

$startTime = Get-Date
$totalPrompts = ($queueState | Where-Object { -not $_.Completed }).Count

Write-Status "Total prompts to process: $totalPrompts" -Color Green
Write-Host ""

while ($true) {
    $nextPrompt = $queueState | Where-Object {
        -not $_.Completed -and $_.Retries -lt $MaxRetries
    } | Select-Object -First 1

    if (-not $nextPrompt) {
        $allCompleted = ($queueState | Where-Object { -not $_.Completed }).Count -eq 0
        if ($allCompleted) {
            Write-Status "All prompts processed successfully!" -Color Green
            break
        }

        $exhausted = $queueState | Where-Object { -not $_.Completed -and $_.Retries -ge $MaxRetries }
        if ($exhausted.Count -gt 0) {
            Write-Status "Warning: $($exhausted.Count) prompt(s) exhausted max retries" -Color Yellow
            foreach ($wp in $exhausted) {
                Write-Host "  - $(Format-PromptName $wp.Path) (retries: $($wp.Retries))" -ForegroundColor Yellow
            }
        }

        $waitedAny = $false
        $now = Get-Date
        foreach ($prompt in $queueState | Where-Object { -not $_.Completed }) {
            if ($prompt.LastRun) {
                $timeSince = ($now - [datetime]$prompt.LastRun).TotalSeconds
                if ($timeSince -lt $RetryDelaySeconds) {
                    $waitRemaining = [math]::Ceiling($RetryDelaySeconds - $timeSince)
                    Write-Status "Cooldown: $(Format-PromptName $prompt.Path) — $waitRemaining s remaining" -Color Yellow
                    $waitedAny = $true
                }
            }
        }

        if ($waitedAny) {
            Start-Sleep -Seconds 30
            continue
        }

        break
    }

    # Check retry cooldown
    if ($nextPrompt.LastRun) {
        $timeSince = ((Get-Date) - [datetime]$nextPrompt.LastRun).TotalSeconds
        if ($timeSince -lt $RetryDelaySeconds) {
            $waitRemaining = [math]::Ceiling($RetryDelaySeconds - $timeSince)
            Write-Status "Waiting ${waitRemaining}s before retry: $(Format-PromptName $nextPrompt.Path)" -Color Yellow
            Start-Sleep -Seconds 30
            continue
        }
    }

    Write-Host "----------------------------------------"
    Write-Host "Processing: $(Format-PromptName $nextPrompt.Path)"
    Write-Host "Retry count: $($nextPrompt.Retries) / $MaxRetries"
    Write-Host "Timeout: $TimeoutSeconds seconds"
    Write-Host ""

    # Run claude non-interactively: pipe file content to claude -p
    $job = Start-Job -ScriptBlock {
        param($promptPath)
        $content = Get-Content $promptPath -Raw -Encoding UTF8
        $output = $content | & claude --dangerously-skip-permissions -p 2>&1 |
            ForEach-Object { $_.ToString() }
        return [PSCustomObject]@{
            Output   = ($output -join "`n")
            ExitCode = $LASTEXITCODE
        }
    } -ArgumentList $nextPrompt.Path

    $timeoutReached = $false
    $elapsed = 0

    while ($true) {
        if ($job.State -eq "Completed" -or $job.State -eq "Failed") {
            break
        }

        if ($elapsed -ge $TimeoutSeconds) {
            $timeoutReached = $true
            Stop-Job $job
            Remove-Job $job
            break
        }

        Start-Sleep -Seconds 5
        $elapsed += 5
        Write-Host "  [$(Get-Date -Format HH:mm:ss)] Running... ($elapsed / $TimeoutSeconds s)"
    }

    if ($timeoutReached) {
        Write-Status "TIMEOUT: $(Format-PromptName $nextPrompt.Path)" -Color Red
        $result = @{
            Success  = $false
            Output   = "Timed out after $TimeoutSeconds seconds"
            ExitCode = 1
        }
    }
    else {
        $jobResult = Receive-Job $job
        Remove-Job $job

        $output   = if ($jobResult -and $jobResult.Output)   { $jobResult.Output }   else { "" }
        $exitCode = if ($jobResult -and $null -ne $jobResult.ExitCode) { $jobResult.ExitCode } else { 1 }

        $result = @{
            Success  = -not (Test-Failure -Output $output -ExitCode $exitCode)
            Output   = $output
            ExitCode = $exitCode
        }
    }

    if ($result.Success) {
        Write-Status "SUCCESS: $(Format-PromptName $nextPrompt.Path)" -Color Green
        $queueState | Where-Object { $_.Path -eq $nextPrompt.Path } | ForEach-Object {
            $_.Completed = $true
            $_.LastRun   = Get-Date -Format "o"
        }
    }
    else {
        Write-Status "FAILED: $(Format-PromptName $nextPrompt.Path)" -Color Red

        if ($result.ExitCode -ne 0) {
            Write-Host "  Exit code: $($result.ExitCode)" -ForegroundColor Red
        }

        $outputLower = $result.Output.ToLower()
        foreach ($pattern in $FailurePatterns) {
            if ($outputLower -match [regex]::Escape($pattern)) {
                Write-Host "  Detected: '$pattern'" -ForegroundColor Yellow
            }
        }

        $queueState | Where-Object { $_.Path -eq $nextPrompt.Path } | ForEach-Object {
            $_.Retries += 1
            $_.LastRun  = Get-Date -Format "o"
        }
    }

    Write-Host ""
    Save-State $StateFile $queueState
    Start-Sleep -Seconds 2
}

$finalElapsed = Get-TimeElapsed $startTime
Write-Host ""
Write-Status "All processing complete!" -Color Green
Write-Status "Total time: $finalElapsed seconds" -Color Gray
