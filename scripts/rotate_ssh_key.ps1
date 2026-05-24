# rotate_ssh_key.ps1 — Safely rotate the id_careerbridge SSH key.
#
# The problem with plain ssh-keygen: it regenerates the private key immediately,
# leaving the VPS authorized_keys out of sync until someone manually pushes the
# new public key. If the tunnel disconnects in that window, auth fails silently.
#
# This script does it atomically:
#   1. Generate new key pair to a TEMP location
#   2. Push new public key to VPS using the CURRENT (still-valid) key
#   3. Verify the new key authenticates successfully
#   4. Only then replace the old key file with the new one
#   5. Restart the tunnel using the new key
#
# Usage:
#   powershell -File D:\cb-core\scripts\rotate_ssh_key.ps1

$keyPath    = "$env:USERPROFILE\.ssh\id_careerbridge"
$keyPubPath = "$keyPath.pub"
$tmpKey     = "$env:TEMP\cb_new_key_$([System.Guid]::NewGuid().ToString('N').Substring(0,8))"
$vps        = "root@77.42.91.185"

# Find a currently-working key to use for the push
$workingKey = @(
    "$env:USERPROFILE\.ssh\id_careerbridge",
    "$env:USERPROFILE\.ssh\cb_remote_agent"
) | Where-Object {
    if (-not (Test-Path $_)) { return $false }
    $r = & ssh -i $_ -o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=no `
        $vps "echo OK" 2>&1
    $r -contains "OK"
} | Select-Object -First 1

if (-not $workingKey) {
    Write-Host "ERROR: No working SSH key found — cannot safely push new key to VPS."
    Write-Host "Fix auth manually first, then re-run this script."
    exit 1
}

Write-Host "Working key: $workingKey"
Write-Host ""

# Step 1: Generate new key pair to temp location
Write-Host "[1/5] Generating new ED25519 key pair..."
& ssh-keygen -t ed25519 -f $tmpKey -N "" -C "careerbridge_$(Get-Date -Format 'yyyyMMdd')" | Out-Null
if (-not (Test-Path "$tmpKey.pub")) {
    Write-Host "ERROR: ssh-keygen failed."
    exit 1
}
$newPub = (Get-Content "$tmpKey.pub").Trim()
Write-Host "      New public key: $newPub"
Write-Host ""

# Step 2: Push new public key to VPS authorized_keys
Write-Host "[2/5] Pushing new public key to VPS..."
$pushResult = & ssh -i $workingKey -o BatchMode=yes -o StrictHostKeyChecking=no $vps `
    "grep -qF '$newPub' ~/.ssh/authorized_keys || echo '$newPub' >> ~/.ssh/authorized_keys && echo PUSHED" 2>&1
if ($pushResult -notcontains "PUSHED" -and $pushResult -notmatch "PUSHED") {
    Write-Host "ERROR: Failed to push key to VPS. Output: $pushResult"
    Remove-Item $tmpKey, "$tmpKey.pub" -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "      Key added to VPS authorized_keys."
Write-Host ""

# Step 3: Verify the new key authenticates
Write-Host "[3/5] Verifying new key authenticates..."
$authTest = & ssh -i $tmpKey -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no `
    $vps "echo AUTH_OK" 2>&1
if ($authTest -notcontains "AUTH_OK") {
    Write-Host "ERROR: New key verification failed. Output: $authTest"
    Write-Host "VPS authorized_keys was updated but auth still fails — manual investigation needed."
    Remove-Item $tmpKey, "$tmpKey.pub" -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "      New key verified OK."
Write-Host ""

# Step 4: Replace old key files atomically
Write-Host "[4/5] Replacing key files..."
if (Test-Path $keyPath)    { Copy-Item $keyPath    "$keyPath.bak"    -Force }
if (Test-Path $keyPubPath) { Copy-Item $keyPubPath "$keyPubPath.bak" -Force }
Move-Item $tmpKey    $keyPath    -Force
Move-Item "$tmpKey.pub" $keyPubPath -Force
Write-Host "      $keyPath replaced (backup: $keyPath.bak)"
Write-Host ""

# Step 5: Restart tunnel with new key
Write-Host "[5/5] Restarting SSH tunnel..."
Get-Process -Name ssh -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

$proc = Start-Process -FilePath "C:\WINDOWS\System32\OpenSSH\ssh.exe" -ArgumentList @(
    "-i", $keyPath,
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=5",
    "-o", "ExitOnForwardFailure=yes",
    "-L", "6380:127.0.0.1:6379",
    "-L", "5433:127.0.0.1:5432",
    "-L", "3101:127.0.0.1:3100",
    "-N", $vps
) -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 5

$portsUp = @(6380, 5433, 3101) | ForEach-Object {
    try { $t=New-Object System.Net.Sockets.TcpClient; $t.Connect("127.0.0.1",$_); $t.Close(); $_ } catch {}
}

Write-Host ""
Write-Host "========================================"
Write-Host "Key rotation COMPLETE"
Write-Host "  New key:    $keyPath"
Write-Host "  Backup:     $keyPath.bak"
Write-Host "  Tunnel PID: $($proc.Id)"
Write-Host "  Ports up:   $($portsUp -join ', ')"
if ($portsUp.Count -eq 3) {
    Write-Host "  Status:     ALL PORTS OPEN - tunnel healthy"
} else {
    Write-Host "  Status:     WARNING - not all ports bound ($((3 - $portsUp.Count)) missing)"
}
Write-Host "========================================"
