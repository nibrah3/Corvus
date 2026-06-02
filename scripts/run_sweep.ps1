# run_sweep.ps1 — CareerBridge 30-minute local system sweep
# Invoked by \CareerBridge_Sweep Windows Task Scheduler task.

$ErrorActionPreference = "SilentlyContinue"
$logFile    = "D:\cb-core\logs\sweep.log"
$promptFile = "D:\cb-core\scripts\SWEEP.md"
$claudeCmd  = "C:\Users\HP\AppData\Roaming\npm\claude.cmd"

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$ts] === Sweep starting ===" | Out-File -Append -FilePath $logFile -Encoding utf8

if (!(Test-Path $promptFile)) {
    "[$ts] ERROR: SWEEP.md not found" | Out-File -Append -FilePath $logFile -Encoding utf8
    exit 1
}
if (!(Test-Path $claudeCmd)) {
    "[$ts] ERROR: claude.cmd not found at $claudeCmd" | Out-File -Append -FilePath $logFile -Encoding utf8
    exit 1
}

$prompt = Get-Content $promptFile -Raw -Encoding utf8

# Invoke claude directly — PowerShell handles arg passing without shell quoting issues
$output = & $claudeCmd --print -p $prompt 2>&1

$output | Out-File -Append -FilePath $logFile -Encoding utf8

$ts2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$ts2] === Sweep complete ===" | Out-File -Append -FilePath $logFile -Encoding utf8
