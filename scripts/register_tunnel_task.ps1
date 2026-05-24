# register_tunnel_task.ps1 — Register ONLY the CareerBridge-Tunnel scheduled task.
# Run ONCE as Administrator:
#   Right-click PowerShell -> "Run as Administrator"
#   powershell -File D:\cb-core\scripts\register_tunnel_task.ps1

$tunnelName   = "CareerBridge-Tunnel"
$tunnelScript = "D:\cb-core\scripts\vps_tunnel.ps1"
$pwshExe      = "powershell.exe"

Unregister-ScheduledTask -TaskName $tunnelName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute $pwshExe `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$tunnelScript`""

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName   $tunnelName `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -Principal  $principal `
    -Description "CareerBridge: SSH tunnel to VPS (Redis:6380, Postgres:5433, Crawlee:3101). Auto-restarts every 1 min on exit."

if ($?) {
    Write-Host "SUCCESS: Task '$tunnelName' registered." -ForegroundColor Green
    Write-Host "Starting it now..."
    Start-ScheduledTask -TaskName $tunnelName
    Start-Sleep -Seconds 3
    (Get-ScheduledTask -TaskName $tunnelName).State
} else {
    Write-Host "FAILED: Check you are running as Administrator." -ForegroundColor Red
}
