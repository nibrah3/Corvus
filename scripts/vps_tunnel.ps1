# vps_tunnel.ps1 — Forward SSH tunnels from Desktop to VPS.
# Opens:
#   localhost:6380 -> VPS:6379  (Redis)
#   localhost:5433 -> VPS:5432  (Postgres)
#   localhost:3101 -> VPS:3100  (Crawlee API)
# Run once; loops to auto-reconnect on disconnect.

$vps    = "root@77.42.91.185"
$sshKey = "$env:USERPROFILE\.ssh\id_rsa"

function Test-PortOpen($port) {
    try {
        $t = New-Object System.Net.Sockets.TcpClient
        $t.Connect("127.0.0.1", $port)
        $t.Close()
        return $true
    } catch { return $false }
}

Write-Host "VPS Tunnel Manager starting..."
Write-Host "  Redis:    localhost:6380 -> VPS:6379"
Write-Host "  Postgres: localhost:5433 -> VPS:5432"
Write-Host "  Crawlee:  localhost:3101 -> VPS:3100"
Write-Host ""

$attempt = 0
while ($true) {
    $attempt++
    if ($attempt -gt 1) {
        Write-Host "$(Get-Date -Format 'HH:mm:ss') Tunnel disconnected. Reconnecting (#$attempt)..."
        Start-Sleep -Seconds 5
    }

    $sshArgs = @(
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=5",
        "-o", "ExitOnForwardFailure=yes",
        "-L", "6380:127.0.0.1:6379",
        "-L", "5433:127.0.0.1:5432",
        "-L", "3101:127.0.0.1:3100",
        "-N",
        $vps
    )

    if (Test-Path $sshKey) {
        $sshArgs = @("-i", $sshKey) + $sshArgs
    }

    Write-Host "$(Get-Date -Format 'HH:mm:ss') Tunnel open."
    & ssh @sshArgs
    Write-Host "$(Get-Date -Format 'HH:mm:ss') Tunnel closed (exit $LASTEXITCODE)."
}
