# register_all_tasks.ps1 — Register all CareerBridge scheduled tasks.
# Run ONCE as Administrator.

$root   = "D:\cb-core"
$pwsh   = "powershell.exe"
$python = "C:\Python314\python.exe"
$claude = "C:\Users\HP\AppData\Roaming\npm\claude.cmd"
$user   = $env:USERNAME

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

# 5. CareerBridge_Sweep — every 30 minutes, system health check
schtasks /delete /tn "CareerBridge_Sweep" /f 2>$null
schtasks /create /tn "CareerBridge_Sweep" `
    /tr "$pwsh -NonInteractive -WindowStyle Hidden -File `"$root\scripts\run_sweep.ps1`"" `
    /sc MINUTE /mo 30 /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge_Sweep"

# 6. CareerBridge_Gate — every 15 min
# Claude Code reads raw_discoveries, gates each item (block/keep/classify),
# writes clean records to jobs table. No Python LLM calls — Claude Code IS the LLM.
schtasks /delete /tn "CareerBridge_Gate" /f 2>$null
schtasks /create /tn "CareerBridge_Gate" `
    /tr "$claude --print --no-confirmation -p `"@$root\prompts\skill_gate_discoveries.md`" >> `"$root\logs\gate.log`" 2>&1" `
    /sc MINUTE /mo 15 /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge_Gate"

# 7. CareerBridge_Catalogue — every 6 hours
# Claude Code polls company catalogue (discovered_platforms), Firecrawls their careers pages,
# finds new listings, gates them, adjusts tiers. Keeps the catalogue alive and self-maintaining.
schtasks /delete /tn "CareerBridge_Catalogue" /f 2>$null
schtasks /create /tn "CareerBridge_Catalogue" `
    /tr "$claude --print --no-confirmation -p `"@$root\prompts\skill_catalogue_poll.md`" >> `"$root\logs\catalogue.log`" 2>&1" `
    /sc HOURLY /mo 6 /ru $user /rl HIGHEST /f /st 03:00
Write-Host "Registered: CareerBridge_Catalogue"

# 8. CareerBridge_WeeklyGap — Mondays 09:00
# Claude Code analyzes the full DB state, identifies gaps in job_type coverage,
# generates targeted search strategy, archives dead platforms.
schtasks /delete /tn "CareerBridge_WeeklyGap" /f 2>$null
schtasks /create /tn "CareerBridge_WeeklyGap" `
    /tr "$claude --print --no-confirmation -p `"@$root\prompts\skill_gap_analysis.md`" >> `"$root\logs\gap_analysis.log`" 2>&1" `
    /sc WEEKLY /d MON /st 09:00 /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge_WeeklyGap"

# 9. CareerBridge-RawListener — logon trigger, Redis push listener
# Fires the gate skill immediately when VPS signals new raw_discoveries.
# Faster than waiting for the 15-min poll.
schtasks /delete /tn "CareerBridge-RawListener" /f 2>$null
schtasks /create /tn "CareerBridge-RawListener" `
    /tr "$python `"$root\scripts\raw_listener.py`"" `
    /sc ONLOGON /ru $user /rl HIGHEST /f
Write-Host "Registered: CareerBridge-RawListener"

Write-Host ""
Write-Host "Starting logon tasks now..."
schtasks /run /tn "CareerBridge-Agent"       2>$null
schtasks /run /tn "CareerBridge-Health"      2>$null
schtasks /run /tn "CareerBridge-Tunnel"      2>$null
schtasks /run /tn "CareerBridge-RawListener" 2>$null
Write-Host "Done."
