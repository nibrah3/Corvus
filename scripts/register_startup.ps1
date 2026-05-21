# register_startup.ps1 — Register CareerBridge agent as a Windows startup task.
# Run this ONCE as Administrator. After that, the agent starts automatically at boot.
#
# NOTE: On the original machine, three stale tasks exist but are harmless (no scripts
# behind them). Do NOT register these on new machines:
#   - CareerBridgeTunnel   (retired — ZeroClaw tunnel, no longer used)
#   - CareerBridgeWorker   (retired — standalone worker, replaced by Claude Code)
#   - CareerBridgeZeroClaw (retired — ZeroClaw removed from project)
# Only register: CareerBridge-Agent and CareerBridgeIXBrowser (done separately).

$taskName   = "CareerBridge-Agent"
$scriptPath = "D:\cb-core\scripts\start_agent.ps1"
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

# ── Health daemon ─────────────────────────────────────────────────────────────

$daemonName    = "CareerBridge-Health"
$daemonWrapper = "$PSScriptRoot\start_health_daemon.ps1"
$pwshExe       = "powershell.exe"

Unregister-ScheduledTask -TaskName $daemonName -Confirm:$false -ErrorAction SilentlyContinue

$daemonAction = New-ScheduledTaskAction `
    -Execute $pwshExe `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$daemonWrapper`"" `
    -WorkingDirectory (Split-Path $PSScriptRoot -Parent)

$daemonSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName   $daemonName `
    -Action     $daemonAction `
    -Trigger    $trigger `
    -Settings   $daemonSettings `
    -Principal  $principal `
    -Description "CareerBridge: health daemon — monitors MCP ports and auto-restarts failed servers"

Write-Host "Task '$daemonName' registered."

# ── VPS Tunnel ────────────────────────────────────────────────────────────────

$tunnelName   = "CareerBridge-Tunnel"
$tunnelScript = "$PSScriptRoot\vps_tunnel.ps1"

Unregister-ScheduledTask -TaskName $tunnelName -Confirm:$false -ErrorAction SilentlyContinue

$tunnelAction = New-ScheduledTaskAction `
    -Execute $pwshExe `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$tunnelScript`""

Register-ScheduledTask `
    -TaskName   $tunnelName `
    -Action     $tunnelAction `
    -Trigger    $trigger `
    -Settings   $daemonSettings `
    -Principal  $principal `
    -Description "CareerBridge: SSH tunnel to VPS (Redis:6380, Postgres:5433, Crawlee:3101)"

Write-Host "Task '$tunnelName' registered."
Write-Host ""
Write-Host "To start all now without rebooting:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  Start-ScheduledTask -TaskName '$daemonName'"
Write-Host "  Start-ScheduledTask -TaskName '$tunnelName'"
