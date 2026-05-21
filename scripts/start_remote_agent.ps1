# start_remote_agent.ps1 — Run once on DESKTOP-5OP0RFK.
# Pulls latest code, sets up SSH key, opens reverse tunnel to VPS, starts remote agent.
# After this script is running, the primary machine's Claude Code session has full control.

$ErrorActionPreference = "Stop"
$cb  = "D:\cb-core"
$vps = "root@77.42.91.185"
$port = 7070
$keyPath = "$env:USERPROFILE\.ssh\cb_remote_agent"

# ── 1. Git pull ───────────────────────────────────────────────────────────────

Write-Host "Pulling latest code..."
Set-Location $cb
git pull origin master

# ── 2. SSH key (pre-generated, VPS already has the public key) ────────────────

if (-not (Test-Path $keyPath)) {
    Write-Host "Writing SSH private key..."
    $keyDir = Split-Path $keyPath
    if (-not (Test-Path $keyDir)) { New-Item -ItemType Directory $keyDir | Out-Null }

    $privateKey = @"
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACCBE6tP7hmHCNn+U4jqfIrNgarFZi+t0/Owg+Q7pdzULwAAAJhTbzVcU281
XAAAAAtzc2gtZWQyNTUxOQAAACCBE6tP7hmHCNn+U4jqfIrNgarFZi+t0/Owg+Q7pdzULw
AAAEDqOnVNzfn+aonQJQz3P8cCwxGP6ZcoAkIYYTtxQHyhk4ETq0/uGYcI2f5TiOp8is2B
qsVmL63T87CD5Dul3NQvAAAAD2NiLXJlbW90ZS1hZ2VudAECAwQFBg==
-----END OPENSSH PRIVATE KEY-----
"@
    [IO.File]::WriteAllText($keyPath, $privateKey.Replace("`r`n", "`n"))
    # Restrict permissions so SSH accepts the key
    icacls $keyPath /inheritance:r /grant:r "$env:USERNAME:F" | Out-Null
}

# ── 3. Reverse SSH tunnel (background) ───────────────────────────────────────

Write-Host "Opening reverse SSH tunnel to VPS ($vps, port $port)..."
$tunnelArgs = @(
    "-i", $keyPath,
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=5",
    "-o", "ExitOnForwardFailure=yes",
    "-NR", "${port}:127.0.0.1:${port}",
    $vps
)
Start-Process -FilePath "ssh" -ArgumentList $tunnelArgs -WindowStyle Hidden
Start-Sleep -Seconds 3
Write-Host "Tunnel open."

# ── 4. Start remote agent (foreground — keep this window open) ───────────────

Write-Host "Starting remote agent on :$port — keep this window open."
Write-Host ""
& "C:\Python314\python.exe" "$cb\scripts\remote_agent.py"
