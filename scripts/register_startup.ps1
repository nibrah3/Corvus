# register_startup.ps1 — Register CareerBridge agent as a Windows startup task.
# Run this ONCE as Administrator. After that, the agent starts automatically at boot.

$taskName   = "CareerBridge-Agent"
$scriptPath = "E:\cb-core\scripts\start_agent.ps1"
$pwsh       = "powershell.exe"

# Remove old version if it exists
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$scriptPath`""

# Trigger: at log-on of any user
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Run with highest privileges, continue on battery
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName   $taskName `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -Principal  $principal `
    -Description "CareerBridge: starts MCP servers and Claude Code Remote Control session on login"

Write-Host ""
Write-Host "Task '$taskName' registered."
Write-Host "It will run automatically at next login."
Write-Host ""
Write-Host "To start it now without rebooting:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
