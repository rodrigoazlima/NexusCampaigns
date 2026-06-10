# Task Scheduler fallback daemon — calls runner.py --once every 60s.
# Prefer NSSM for production installs: runner.py runs its own loop when
# invoked without --once.
#
# Usage: powershell -NonInteractive -File daemon.ps1
# API keys and GIT_AUTHOR_* must be set in the Task Scheduler environment
# or in the system/user environment before launching this script.

param(
    [string]$ProjectRoot = "C:\opt\GitHub\NexusCampaigns",
    [string]$Python      = "python",
    [int]   $IntervalSec = 60
)

$Runner = "$ProjectRoot\.agents\runtime\tools\runner.py"

while ($true) {
    & $Python $Runner --once
    Start-Sleep -Seconds $IntervalSec
}
