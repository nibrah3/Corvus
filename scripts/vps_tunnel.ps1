# vps_tunnel.ps1 — Forward SSH tunnels from Desktop to VPS.
# Opens:
#   localhost:6380 -> VPS:6379  (Redis)
#   localhost:5433 -> VPS:5432  (Postgres)
#   localhost:3101 -> VPS:3100  (Crawlee API)
#
# Uses cb_tunnel — the PERMANENT, NEVER-ROTATED tunnel key.
# SSH host config is in ~/.ssh/config (Host cb-vps).
# Run once; loops to auto-reconnect on disconnect.

$vps    = "cb-vps"    # resolved by ~/.ssh/config -> 77.42.91.185 via cb_tunnel key
$sshKey = "$env:USERPROFILE\.ssh\cb_tunnel"

$AlertAfterFailures = 3
$ReconnectDelaySec  = 5

# ── Load env for Telegram ──────────────────────────────────────────────────────
foreach ($envFile in @("D:\cb-core\.env", "D:\cb-core\runtime\.env")) {
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^([^#=]+)=(.+)$') {
                $k = $Matches[1].Trim(); $v = $Matches[2].Trim()
                if (-not [System.Environment]::GetEnvironmentVariable($k)) {
                    [System.Environment]::SetEnvironmentVariable($k, $v)
                }
            }
        }
        break
    }
}

function Send-TelegramAlert($text) {
    $token  = $env:TELEGRAM_BOT_TOKEN
    $chatId = $env:TELEGRAM_ADMIN_CHAT_ID
    if (-not $token -or -not $chatId) { return }
    try {
        $body = @{ chat_id = [long]$chatId; text = $text } | ConvertTo-Json
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -Method Post -ContentType "application/json" -Body $body -TimeoutSec 8 | Out-Null
    } catch {}
}

function Test-PortOpen($port) {
    try {
        $t = New-Object System.Net.Sockets.TcpClient
        $t.Connect("127.0.0.1", $port)
        $t.Close()
        return $true
    } catch { return $false }
}

Write-Host "VPS Tunnel Manager starting..."
Write-Host "  Key:      $sshKey (PERMANENT — never rotate)"
Write-Host "  Host:     $vps -> 77.42.91.185"
Write-Host "  Redis:    localhost:6380 -> VPS:6379"
Write-Host "  Postgres: localhost:5433 -> VPS:5432"
Write-Host "  Crawlee:  localhost:3101 -> VPS:3100"
Write-Host ""

if (-not (Test-Path $sshKey)) {
    Write-Host "ERROR: cb_tunnel key not found at $sshKey"
    Write-Host "Run setup: ssh-keygen -t ed25519 -f $sshKey -N '""""' -C cb-tunnel-permanent"
    exit 1
}

$attempt          = 0
$consecutiveFails = 0
$alertSent        = $false

while ($true) {
    $attempt++
    if ($attempt -gt 1) {
        Write-Host "$(Get-Date -Format 'HH:mm:ss') Tunnel disconnected. Reconnecting (#$attempt)..."
        Start-Sleep -Seconds $ReconnectDelaySec
    }

    $sshArgs = @(
        "-i", $sshKey,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=5",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "TCPKeepAlive=yes",
        "-L", "6380:127.0.0.1:6379",
        "-L", "5433:127.0.0.1:5432",
        "-L", "3101:127.0.0.1:3100",
        "-N",
        "root@77.42.91.185"
    )

    Write-Host "$(Get-Date -Format 'HH:mm:ss') Connecting..."
    $t0 = [System.Diagnostics.Stopwatch]::StartNew()

    & ssh @sshArgs

    $exitCode = $LASTEXITCODE
    $aliveSec = [int]$t0.Elapsed.TotalSeconds
    $t0.Stop()

    Write-Host "$(Get-Date -Format 'HH:mm:ss') SSH exited (code=$exitCode, uptime=${aliveSec}s)."

    if ($aliveSec -lt 8) {
        $consecutiveFails++
        Write-Host "$(Get-Date -Format 'HH:mm:ss') Short-lived — possible auth/port failure (fail #$consecutiveFails)."
        if ($consecutiveFails -ge $AlertAfterFailures -and -not $alertSent) {
            $alertSent = $true
            Send-TelegramAlert (
                "[TUNNEL] VPS SSH tunnel failed $consecutiveFails consecutive times (code=$exitCode). " +
                "Key: $sshKey. Check VPS authorized_keys."
            )
        }
    } else {
        if ($consecutiveFails -gt 0) {
            Write-Host "$(Get-Date -Format 'HH:mm:ss') Tunnel recovered after $consecutiveFails failure(s)."
            Send-TelegramAlert "[TUNNEL] VPS SSH tunnel recovered after $consecutiveFails failure(s)."
        }
        $consecutiveFails = 0
        $alertSent        = $false
    }
}
