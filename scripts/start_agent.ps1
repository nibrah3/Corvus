# start_agent.ps1 — Keep Claude Code Remote Control session alive permanently.
# Starts the MCPs first, then loops Claude Code with Remote Control enabled.
# When the session exits for any reason, it restarts automatically.
#
# The session is named "CareerBridge" — find it in the Claude app session list.
# Connect from your phone: open the Claude app -> Sessions -> CareerBridge

Set-Location "E:\cb-core"

# Start MCP servers first (skips any already running)
Write-Host "Starting MCP servers..."
& "E:\cb-core\scripts\start_mcps.ps1"
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "Starting Claude Code Remote Control (session: CareerBridge)..."
Write-Host "Connect from your phone via the Claude app -> Sessions"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

$restarts = 0
while ($true) {
    $restarts++
    if ($restarts -gt 1) {
        Write-Host "$(Get-Date -Format 'HH:mm:ss') Session ended. Restarting (#$restarts)..."
        Start-Sleep -Seconds 5
    }

    # --continue resumes the most recent conversation for persistent context
    # --dangerously-skip-permissions lets the agent act autonomously
    claude --remote-control "CareerBridge" --continue --dangerously-skip-permissions
}
