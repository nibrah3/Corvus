# register_all_tasks.ps1 — Register all 5 CareerBridge scheduled tasks.
# Run ONCE as Administrator.

$root   = "D:\cb-core"
$pwsh   = "powershell.exe"
$python = "C:\Python314\python.exe"
$user   = $env:USERNAME

function Register-CB-Task {
    param(
        [string]$Name,
        [string]$Exe,
        [string]$Args,
        [string]$WorkDir,
        [string]$Schedule,
        [string]$Desc
    )

    schtasks /delete /tn $Name /f 2>$null

    $cmd = "schtasks /create /tn `"$Name`" /tr `"'$Exe' $Args`" /sc $Schedule /ru $user /rl HIGHEST /f"
    if ($WorkDir) { $cmd += " /sd `"$WorkDir`"" }

    Invoke-Expression $cmd
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Registered: $Name"
    } else {
        Write-Host "FAILED: $Name" -ForegroundColor Red
    }
}

# 1. CareerBridge-Agent — logon trigger, starts MCPs + remote control
schtasks /delete /tn "CareerBridge-Agent" /f 2>$null
schtasks /create /tn "CareerBridge-Agent" `
    /tr "$pwsh -NonInteractive -WindowStyle Hidden -File `"$root\scripts\start_agent.ps1`"" `
    /sc ONLOGON /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge-Agent"

# 2. CareerBridge-Health — logon trigger, health daemon
schtasks /delete /tn "CareerBridge-Health" /f 2>$null
schtasks /create /tn "CareerBridge-Health" `
    /tr "$pwsh -NonInteractive -WindowStyle Hidden -File `"$root\scripts\start_health_daemon.ps1`"" `
    /sc ONLOGON /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge-Health"

# 3. CareerBridge-Tunnel — logon trigger, SSH tunnel
schtasks /delete /tn "CareerBridge-Tunnel" /f 2>$null
schtasks /create /tn "CareerBridge-Tunnel" `
    /tr "$pwsh -NonInteractive -WindowStyle Hidden -File `"$root\scripts\vps_tunnel.ps1`"" `
    /sc ONLOGON /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge-Tunnel"

# 4. CareerBridge_SchoolReport_6h — every 6 hours
schtasks /delete /tn "CareerBridge_SchoolReport_6h" /f 2>$null
schtasks /create /tn "CareerBridge_SchoolReport_6h" `
    /tr "$python `"$root\scripts\school_report_cron.py`"" `
    /sc HOURLY /mo 6 /ru $user /rl HIGHEST /f /st 06:00
Write-Host "Registered: CareerBridge_SchoolReport_6h"

# 5. CareerBridge_Sweep — every 30 minutes
schtasks /delete /tn "CareerBridge_Sweep" /f 2>$null
schtasks /create /tn "CareerBridge_Sweep" `
    /tr "$pwsh -NonInteractive -WindowStyle Hidden -File `"$root\scripts\run_sweep.ps1`"" `
    /sc MINUTE /mo 30 /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge_Sweep"

# 6. CareerBridge_Gate — every 15 minutes, gates new discoveries through Claude
# Picks up any jobs discovered since last run and gates them (blocks professional roles,
# assigns job_type, resolves official URL). Runs silently; logs to logs\gate.log.
schtasks /delete /tn "CareerBridge_Gate" /f 2>$null
schtasks /create /tn "CareerBridge_Gate" `
    /tr "$python `"$root\scripts\enrich_jobs.py`" >> `"$root\logs\gate.log`" 2>&1" `
    /sc MINUTE /mo 15 /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge_Gate"

Write-Host ""
Write-Host "Starting logon tasks now..."
schtasks /run /tn "CareerBridge-Agent"  2>$null
schtasks /run /tn "CareerBridge-Health" 2>$null
schtasks /run /tn "CareerBridge-Tunnel" 2>$null
Write-Host "Done."
