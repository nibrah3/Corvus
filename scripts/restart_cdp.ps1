Set-Location "D:\cb-core"
$py = "C:\Python314\python.exe"
$conn = Get-NetTCPConnection -LocalPort 8712 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}
Start-Process -FilePath $py -ArgumentList "-m", "cdp_mcp.server", "--http", "8712" -WorkingDirectory "D:\cb-core" -WindowStyle Hidden
